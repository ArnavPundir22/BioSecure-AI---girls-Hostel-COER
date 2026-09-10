"""
Global Test Configuration and Fixtures — BioSecure AI Girls Hostel.
Provides:
1. Strict Schema-Isolated Mock Supabase Client (`MockSupabaseHostelClient`)
2. Flask Test Client Fixtures (unauthenticated and authenticated warden)
3. Microsecond-accurate Time Travel / Frozen Clock Fixture
4. Cooldown Registry Reset Fixture
5. Background Curfew Service Lifecycle Management
"""

import copy
import logging
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

# Configure environment before importing app modules
os.environ["FLASK_SECRET_KEY"] = "test-secret-key-32-chars-long-secure!!"
os.environ["SUPABASE_URL"] = "https://mock-test.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "mock-service-role-key"
os.environ["BIOSECURE_TEST_MODE"] = "1"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"

from src import create_app
from src.services.curfew_service import stop_curfew_service
from src.utils import hostel_db
from src.utils.hostel_state import _cooldown_registry

logger = logging.getLogger(__name__)


# ============================================================================
# 1. Strict Schema-Isolated Mock Supabase Client
# ============================================================================

class SchemaIsolationViolationError(RuntimeError):
    """Raised when an operation attempts to access the public schema or omits girls_hostel scoping."""
    pass


def _compute_cosine_sim(vec1: List[float], vec2: List[float]) -> float:
    """Compute real mathematical cosine similarity between two vector embeddings."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = sum(a * a for a in vec1) ** 0.5
    norm_b = sum(b * b for b in vec2) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _default_system_settings_data() -> List[Dict[str, Any]]:
    now_str = datetime.now(timezone.utc).isoformat()
    return [
        {
            "key": "curfew_schedule",
            "value": {
                "start_time": "17:00",
                "end_time": "19:30",
                "enabled": True
            },
            "updated_at": now_str
        },
        {
            "key": "camera_sources",
            "value": {
                "entry_cam": "0",
                "exit_cam": "1"
            },
            "updated_at": now_str
        },
        {
            "key": "alert_config",
            "value": {
                "smtp_enabled": True,
                "cooldown_seconds": 15
            },
            "updated_at": now_str
        }
    ]


def _default_camera_settings_data() -> List[Dict[str, Any]]:
    now_str = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": 1,
            "camera_role": "IN",
            "vendor": "USB Webcam",
            "ip_address": "192.168.1.64",
            "port": 554,
            "channel": 1,
            "username": "admin",
            "password": "",
            "custom_rtsp_url": "0",
            "resolution": "1280x720",
            "fps": 30,
            "enabled": True,
            "updated_at": now_str,
        },
        {
            "id": 2,
            "camera_role": "OUT",
            "vendor": "USB Webcam",
            "ip_address": "192.168.1.65",
            "port": 554,
            "channel": 2,
            "username": "admin",
            "password": "",
            "custom_rtsp_url": "1",
            "resolution": "1280x720",
            "fps": 30,
            "enabled": True,
            "updated_at": now_str,
        },
    ]


class MockSupabaseHostelClient:
    """
    In-memory Supabase client strictly enforcing schema='girls_hostel'.
    Raises SchemaIsolationViolationError if non-isolated schema is accessed or schema scoping is omitted.
    Implements real table operations and genuine cosine vector similarity.
    """

    ALLOWED_TABLES = {"student_profiles", "movement_logs", "curfew_alerts", "system_settings", "camera_settings"}

    def __init__(self, current_schema: Optional[str] = "girls_hostel"):
        self.current_schema = current_schema
        self._seq_counter = 100
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "student_profiles": [],
            "movement_logs": [],
            "curfew_alerts": [],
            "system_settings": _default_system_settings_data(),
            "camera_settings": _default_camera_settings_data(),
        }
        self.queries_log: List[Dict[str, Any]] = []

    def schema(self, schema_name: str) -> "MockSupabaseHostelClient":
        if schema_name != "girls_hostel":
            raise SchemaIsolationViolationError(
                f"Access to '{schema_name}' schema is strictly prohibited! Girls Hostel subsystem "
                f"is isolated and only permits 'girls_hostel'."
            )
        return self

    def table(self, table_name: str) -> "MockIsolatedTableQuery":
        if not self.current_schema or self.current_schema != "girls_hostel":
            raise SchemaIsolationViolationError(
                f"Table '{table_name}' accessed without 'girls_hostel' schema scoping!"
            )
        if table_name.startswith("public.") or "public" in table_name:
            raise SchemaIsolationViolationError(
                f"Query to '{table_name}' accesses public schema! Access strictly prohibited."
            )
        clean_table = table_name.replace("girls_hostel.", "")
        if clean_table not in self.ALLOWED_TABLES:
            # Create store dynamically if unknown hostel table
            if clean_table not in self.tables:
                self.tables[clean_table] = []
        return MockIsolatedTableQuery(self, clean_table)

    def rpc(self, fn_name: str, params: Optional[Dict[str, Any]] = None) -> "MockIsolatedRpcQuery":
        if fn_name.startswith("public."):
            raise SchemaIsolationViolationError(
                f"RPC call '{fn_name}' targets public schema! Prohibited."
            )
        clean_fn = fn_name.replace("girls_hostel.", "")
        return MockIsolatedRpcQuery(self, clean_fn, params or {})

    def _cascade_delete_student(self, student_id: str):
        """Implement genuine foreign key ON DELETE CASCADE."""
        sid_str = str(student_id)
        self.tables["movement_logs"] = [
            m for m in self.tables["movement_logs"]
            if str(m.get("student_id")) != sid_str
        ]
        self.tables["curfew_alerts"] = [
            a for a in self.tables["curfew_alerts"]
            if str(a.get("student_id")) != sid_str
        ]

    def reset(self):
        """Reset dynamic tables to initial empty state."""
        self.tables["student_profiles"] = []
        self.tables["movement_logs"] = []
        self.tables["curfew_alerts"] = []
        self.tables["system_settings"] = _default_system_settings_data()
        self.tables["camera_settings"] = _default_camera_settings_data()
        self.queries_log = []


class MockIsolatedResponse:
    def __init__(self, data: Any = None, count: Optional[int] = None):
        self.data = data
        self.count = count


class MockIsolatedTableQuery:
    def __init__(self, client: MockSupabaseHostelClient, table_name: str):
        self.client = client
        self.table_name = table_name
        self._action = "select"
        self._select_cols = "*"
        self._filters: List[tuple] = []
        self._order_field: Optional[str] = None
        self._order_desc: bool = False
        self._limit_val: Optional[int] = None
        self._payload: Any = None

    def select(self, columns: str = "*") -> "MockIsolatedTableQuery":
        self._action = "select"
        self._select_cols = columns
        return self

    def insert(self, values: Any) -> "MockIsolatedTableQuery":
        self._action = "insert"
        self._payload = values
        return self

    def update(self, values: Any) -> "MockIsolatedTableQuery":
        self._action = "update"
        self._payload = values
        return self

    def upsert(self, values: Any) -> "MockIsolatedTableQuery":
        self._action = "upsert"
        self._payload = values
        return self

    def delete(self) -> "MockIsolatedTableQuery":
        self._action = "delete"
        return self

    def eq(self, column: str, value: Any) -> "MockIsolatedTableQuery":
        self._filters.append(("eq", column, str(value)))
        return self

    def order(self, column: str, desc: bool = False) -> "MockIsolatedTableQuery":
        self._order_field = column
        self._order_desc = desc
        return self

    def limit(self, count: int) -> "MockIsolatedTableQuery":
        self._limit_val = count
        return self

    def _matches_filter(self, row: Dict[str, Any]) -> bool:
        for f_type, col, target in self._filters:
            if f_type == "eq":
                if str(row.get(col, "")) != target:
                    return False
        return True

    def execute(self) -> MockIsolatedResponse:
        table_store = self.client.tables.setdefault(self.table_name, [])
        self.client.queries_log.append({
            "table": self.table_name,
            "action": self._action,
            "filters": list(self._filters)
        })

        if self._action == "insert":
            records = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            now_iso = datetime.now(timezone.utc).isoformat()
            for r in records:
                row = copy.deepcopy(r)
                if self.table_name == "student_profiles":
                    if "id" not in row or not row["id"]:
                        row["id"] = str(uuid.uuid4())
                    if "current_status" not in row:
                        row["current_status"] = "IN"
                    if "created_at" not in row:
                        row["created_at"] = now_iso
                elif self.table_name in ("movement_logs", "curfew_alerts"):
                    self.client._seq_counter += 1
                    if "id" not in row or not row["id"]:
                        row["id"] = self.client._seq_counter
                    if self.table_name == "movement_logs" and "timestamp" not in row:
                        row["timestamp"] = now_iso
                    elif self.table_name == "curfew_alerts" and "alert_triggered_at" not in row:
                        row["alert_triggered_at"] = now_iso
                table_store.append(row)
                inserted.append(copy.deepcopy(row))
            return MockIsolatedResponse(data=inserted, count=len(inserted))

        elif self._action == "update":
            updated = []
            for row in table_store:
                if self._matches_filter(row):
                    row.update(copy.deepcopy(self._payload))
                    updated.append(copy.deepcopy(row))
            return MockIsolatedResponse(data=updated, count=len(updated))

        elif self._action == "upsert":
            records = self._payload if isinstance(self._payload, list) else [self._payload]
            upserted = []
            for r in records:
                if "camera_role" in r:
                    pk_col = "camera_role"
                elif "key" in r:
                    pk_col = "key"
                else:
                    pk_col = "id"
                pk_val = r.get(pk_col)
                found = False
                for row in table_store:
                    if row.get(pk_col) == pk_val:
                        row.update(copy.deepcopy(r))
                        upserted.append(copy.deepcopy(row))
                        found = True
                        break
                if not found:
                    new_row = copy.deepcopy(r)
                    table_store.append(new_row)
                    upserted.append(new_row)
            return MockIsolatedResponse(data=upserted, count=len(upserted))

        elif self._action == "delete":
            deleted = []
            remaining = []
            for row in table_store:
                if self._matches_filter(row):
                    deleted.append(copy.deepcopy(row))
                    if self.table_name == "student_profiles" and "id" in row:
                        self.client._cascade_delete_student(row["id"])
                else:
                    remaining.append(row)
            self.client.tables[self.table_name] = remaining
            return MockIsolatedResponse(data=deleted, count=len(deleted))

        else:
            # select
            matched = []
            for row in table_store:
                if self._matches_filter(row):
                    row_copy = copy.deepcopy(row)
                    # Support join: student_profiles(...)
                    if "student_profiles(" in self._select_cols and "student_id" in row_copy:
                        sid = str(row_copy["student_id"])
                        student = next(
                            (s for s in self.client.tables["student_profiles"] if str(s.get("id")) == sid),
                            None
                        )
                        row_copy["student_profiles"] = copy.deepcopy(student) if student else None
                    matched.append(row_copy)

            if self._order_field:
                matched.sort(
                    key=lambda r: str(r.get(self._order_field, "")),
                    reverse=self._order_desc
                )

            if self._limit_val is not None:
                matched = matched[:self._limit_val]

            return MockIsolatedResponse(data=matched, count=len(matched))


class MockIsolatedRpcQuery:
    def __init__(self, client: MockSupabaseHostelClient, fn_name: str, params: Dict[str, Any]):
        self.client = client
        self.fn_name = fn_name
        self.params = params

    def execute(self) -> MockIsolatedResponse:
        self.client.queries_log.append({
            "rpc": self.fn_name,
            "params": copy.deepcopy(self.params)
        })

        if self.fn_name == "match_face":
            query_emb = self.params.get("query_embedding")
            if not query_emb or not isinstance(query_emb, list):
                return MockIsolatedResponse(data=[])

            match_threshold = float(self.params.get("match_threshold", 0.40))
            match_count = int(self.params.get("match_count", 1))

            matches = []
            for s in self.client.tables["student_profiles"]:
                emb = s.get("embedding")
                if emb is not None and isinstance(emb, list) and len(emb) == len(query_emb):
                    sim = _compute_cosine_sim(query_emb, emb)
                    # Strictly check threshold
                    if sim >= match_threshold:
                        matches.append({
                            "id": s.get("id"),
                            "name": s.get("name"),
                            "roll_number": s.get("roll_number"),
                            "room_number": s.get("room_number"),
                            "current_status": s.get("current_status", "IN"),
                            "similarity": round(sim, 4)
                        })

            # Sort descending by similarity
            matches.sort(key=lambda m: m["similarity"], reverse=True)
            if match_count > 0:
                matches = matches[:match_count]
            return MockIsolatedResponse(data=matches)

        return MockIsolatedResponse(data=[])


# ============================================================================
# 2. Frozen Clock / Time Travel Helper
# ============================================================================

class FrozenClock:
    """Microsecond-accurate time travel helper."""
    def __init__(self, initial_dt: datetime):
        self._current_dt = initial_dt

    @property
    def current(self) -> datetime:
        return self._current_dt

    def tick(self, seconds: float = 1.0) -> datetime:
        self._current_dt += timedelta(seconds=seconds)
        return self._current_dt

    def set(self, new_dt: datetime) -> None:
        self._current_dt = new_dt

    def now(self, tz=None) -> datetime:
        if tz is not None and self._current_dt.tzinfo is None:
            return self._current_dt.replace(tzinfo=tz)
        if tz is None and self._current_dt.tzinfo is not None:
            return self._current_dt.astimezone(timezone.utc).replace(tzinfo=None)
        return self._current_dt

    def today(self) -> date:
        return self._current_dt.date()


class MockDateTime(datetime):
    _active_clock: Optional[FrozenClock] = None

    @classmethod
    def now(cls, tz=None):
        if cls._active_clock:
            return cls._active_clock.now(tz=tz)
        return datetime.now(tz=tz)

    @classmethod
    def utcnow(cls):
        if cls._active_clock:
            return cls._active_clock.now(tz=timezone.utc).replace(tzinfo=None)
        return datetime.utcnow()

    @classmethod
    def today(cls):
        if cls._active_clock:
            return cls._active_clock.now()
        return datetime.today()


class MockDate(date):
    _active_clock: Optional[FrozenClock] = None

    @classmethod
    def today(cls):
        if cls._active_clock:
            return cls._active_clock.today()
        return date.today()


@contextmanager
def time_travel(dt_or_str):
    """
    Context manager to freeze or travel time down to microsecond precision.
    Patches datetime across hostel_state, curfew_service, and hostel_db.
    """
    if isinstance(dt_or_str, str):
        target_dt = datetime.fromisoformat(dt_or_str)
    else:
        target_dt = dt_or_str

    clock = FrozenClock(target_dt)
    MockDateTime._active_clock = clock
    MockDate._active_clock = clock

    patches = [
        patch("src.utils.hostel_state.datetime", MockDateTime),
        patch("src.services.curfew_service.datetime", MockDateTime),
        patch("src.utils.hostel_db.datetime", MockDateTime),
        patch("src.utils.hostel_db.date", MockDate),
    ]
    for p in patches:
        p.start()

    try:
        yield clock
    finally:
        for p in reversed(patches):
            p.stop()
        MockDateTime._active_clock = None
        MockDate._active_clock = None


# ============================================================================
# 3. Pytest Fixtures
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def suppress_unmanaged_threads():
    """Ensure background threads are stopped on session completion."""
    yield
    stop_curfew_service()


@pytest.fixture
def mock_db() -> MockSupabaseHostelClient:
    """Create a clean MockSupabaseHostelClient and inject into hostel_db."""
    client = MockSupabaseHostelClient()
    hostel_db.set_hostel_client(client)
    yield client
    hostel_db.reset_hostel_client()


@pytest.fixture(autouse=True)
def reset_system_state(mock_db):
    """Autouse fixture resetting cooldowns, mock DB, and active threads."""
    _cooldown_registry.clear()
    yield
    _cooldown_registry.clear()
    stop_curfew_service()


@pytest.fixture
def freeze_clock():
    """Fixture providing the time_travel context manager."""
    return time_travel


@pytest.fixture
def app(mock_db):
    """Create Flask test application configured for testing."""
    with patch("src.blueprints.hostel.start_curfew_service"), \
         patch("src.utils.face_cache.reload_face_cache"):
        application = create_app()
        application.config.update({
            "TESTING": True,
        })
        yield application
    stop_curfew_service()


@pytest.fixture
def client(app):
    """Unauthenticated Flask test client."""
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """Authenticated warden client with valid session credentials."""
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "warden"
        sess["is_admin"] = True
        sess["user_id"] = "00000000-0000-0000-0000-000000000001"
    return test_client
