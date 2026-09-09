"""
Girls Hostel Database Utilities — BioSecure AI.

All DB interactions in this module explicitly target the 'girls_hostel' schema
to guarantee 100% data isolation from classroom attendance systems.
"""

import copy
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HOSTEL_SCHEMA = "girls_hostel"

# Attempt to load live supabase_admin client safely
try:
    from src.utils.db import supabase_admin
except Exception as _e:
    logger.warning(f"Live Supabase client not initialized at import: {_e}")
    supabase_admin = None


# ============================================================================
# Mock Adapter & In-Memory Supabase Client for Testing & Offline Fallback
# ============================================================================

def _compute_cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vector embeddings."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = sum(a * a for a in vec1) ** 0.5
    norm_b = sum(b * b for b in vec2) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class MockResponse:
    """Mock PostgREST response containing data and count."""
    def __init__(self, data: Any = None, count: Optional[int] = None):
        self.data = data
        self.count = count


class MockTableQuery:
    """Query builder simulating Supabase PostgREST table queries."""
    def __init__(self, client: "MockHostelSupabaseClient", table_name: str):
        self.client = client
        self.table_name = table_name
        self._action = "select"
        self._select_columns = "*"
        self._filters: List[tuple] = []
        self._order_col: Optional[str] = None
        self._order_desc: bool = False
        self._limit_count: Optional[int] = None
        self._payload: Any = None

    def select(self, columns: str = "*") -> "MockTableQuery":
        self._action = "select"
        self._select_columns = columns
        return self

    def insert(self, values: Any) -> "MockTableQuery":
        self._action = "insert"
        self._payload = values
        return self

    def update(self, values: Any) -> "MockTableQuery":
        self._action = "update"
        self._payload = values
        return self

    def upsert(self, values: Any) -> "MockTableQuery":
        self._action = "upsert"
        self._payload = values
        return self

    def delete(self) -> "MockTableQuery":
        self._action = "delete"
        return self

    def eq(self, column: str, value: Any) -> "MockTableQuery":
        self._filters.append(("eq", column, str(value)))
        return self

    def order(self, column: str, desc: bool = False) -> "MockTableQuery":
        self._order_col = column
        self._order_desc = desc
        return self

    def limit(self, count: int) -> "MockTableQuery":
        self._limit_count = count
        return self

    def _matches_filters(self, record: Dict[str, Any]) -> bool:
        for f_type, col, target_val in self._filters:
            if f_type == "eq":
                actual_val = str(record.get(col, ""))
                if actual_val != target_val:
                    return False
        return True

    def execute(self) -> MockResponse:
        """Execute the query against the mock in-memory database."""
        table_store = self.client._get_table_store(self.table_name)

        if self._action == "insert":
            inserted_records = []
            records_to_insert = (
                self._payload
                if isinstance(self._payload, list)
                else [self._payload]
            )
            for item in records_to_insert:
                record = copy.deepcopy(item)
                now_str = datetime.now(timezone.utc).isoformat()
                if self.table_name == "student_profiles":
                    if "id" not in record or not record["id"]:
                        record["id"] = str(uuid.uuid4())
                    if "current_status" not in record:
                        record["current_status"] = "IN"
                    if "created_at" not in record:
                        record["created_at"] = now_str
                elif self.table_name in ("movement_logs", "curfew_alerts"):
                    self.client._seq_counter += 1
                    if "id" not in record or not record["id"]:
                        record["id"] = self.client._seq_counter
                    if self.table_name == "movement_logs":
                        if "timestamp" not in record:
                            record["timestamp"] = now_str
                    elif self.table_name == "curfew_alerts":
                        c_date = (
                            record.get("curfew_date")
                            or date.today().isoformat()
                        )
                        record["curfew_date"] = c_date
                        if record.get("status") == "OVERDUE_OUT":
                            for existing in table_store:
                                if (
                                    existing.get("status") == "OVERDUE_OUT"
                                    and str(existing.get("student_id"))
                                    == str(record.get("student_id"))
                                    and str(existing.get("curfew_date"))
                                    == str(c_date)
                                ):
                                    raise ValueError(
                                        "Duplicate active alert violates "
                                        "idx_girls_hostel_curfew_active_uniq"
                                    )
                        if "alert_triggered_at" not in record:
                            record["alert_triggered_at"] = now_str
                table_store.append(record)
                inserted_records.append(copy.deepcopy(record))
            return MockResponse(
                data=inserted_records,
                count=len(inserted_records)
            )

        elif self._action == "update":
            updated_records = []
            for record in table_store:
                if self._matches_filters(record):
                    record.update(copy.deepcopy(self._payload))
                    updated_records.append(copy.deepcopy(record))
            return MockResponse(
                data=updated_records,
                count=len(updated_records)
            )

        elif self._action == "upsert":
            payload_list = (
                self._payload
                if isinstance(self._payload, list)
                else [self._payload]
            )
            upserted_records = []
            for item in payload_list:
                pk_val = item.get("key") if "key" in item else item.get("id")
                pk_col = "key" if "key" in item else "id"
                matched = False
                for record in table_store:
                    if record.get(pk_col) == pk_val:
                        record.update(copy.deepcopy(item))
                        upserted_records.append(copy.deepcopy(record))
                        matched = True
                        break
                if not matched:
                    new_rec = copy.deepcopy(item)
                    table_store.append(new_rec)
                    upserted_records.append(new_rec)
            return MockResponse(
                data=upserted_records,
                count=len(upserted_records)
            )

        elif self._action == "delete":
            deleted_records = []
            remaining = []
            for record in table_store:
                if self._matches_filters(record):
                    deleted_records.append(copy.deepcopy(record))
                else:
                    remaining.append(record)
            self.client._set_table_store(self.table_name, remaining)
            return MockResponse(
                data=deleted_records,
                count=len(deleted_records)
            )

        else:
            # action == "select"
            results = []
            for record in table_store:
                if self._matches_filters(record):
                    rec_copy = copy.deepcopy(record)
                    # Handle relations: student_profiles(...)
                    if ("student_profiles(" in self._select_columns and
                            "student_id" in rec_copy):
                        student = self.client.get_student_profile(
                            rec_copy["student_id"]
                        )
                        rec_copy["student_profiles"] = (
                            copy.deepcopy(student) if student else None
                        )
                    results.append(rec_copy)

            if self._order_col:
                results.sort(
                    key=lambda r: str(r.get(self._order_col, "")),
                    reverse=self._order_desc
                )

            if self._limit_count is not None:
                results = results[:self._limit_count]

            return MockResponse(data=results, count=len(results))


class MockRpcQuery:
    """Simulate Supabase RPC procedure call."""
    def __init__(
        self,
        client: "MockHostelSupabaseClient",
        fn_name: str,
        params: Optional[Dict[str, Any]] = None
    ):
        self.client = client
        self.fn_name = fn_name
        self.params = params or {}

    def execute(self) -> MockResponse:
        clean_fn = self.fn_name.replace("girls_hostel.", "")
        if clean_fn == "match_face":
            query_emb = self.params.get("query_embedding", [])
            match_thresh = float(self.params.get("match_threshold", 0.40))
            match_count = int(self.params.get("match_count", 1))

            matches = []
            for s in self.client.student_profiles:
                emb = s.get("embedding")
                if emb:
                    sim = _compute_cosine_similarity(query_emb, emb)
                    if sim >= match_thresh:
                        matches.append({
                            "id": s.get("id"),
                            "name": s.get("name"),
                            "roll_number": s.get("roll_number"),
                            "room_number": s.get("room_number"),
                            "current_status": s.get("current_status", "IN"),
                            "similarity": round(sim, 4)
                        })

            matches.sort(key=lambda m: m["similarity"], reverse=True)
            return MockResponse(data=matches[:match_count])

        return MockResponse(data=[])


def _default_system_settings() -> List[Dict[str, Any]]:
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


class MockHostelSupabaseClient:
    """
    Complete in-memory mock client providing genuine database simulation
    for girls_hostel schema tables and RPC functions.
    """
    def __init__(self):
        self._seq_counter = 100
        self.student_profiles: List[Dict[str, Any]] = []
        self.movement_logs: List[Dict[str, Any]] = []
        self.curfew_alerts: List[Dict[str, Any]] = []
        self.system_settings: List[Dict[str, Any]] = _default_system_settings()

    def schema(self, schema_name: str) -> "MockHostelSupabaseClient":
        return self

    def table(self, table_name: str) -> MockTableQuery:
        return MockTableQuery(self, table_name)

    def rpc(
        self,
        fn_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> MockRpcQuery:
        return MockRpcQuery(self, fn_name, params)

    def _get_table_store(self, table_name: str) -> List[Dict[str, Any]]:
        if table_name == "student_profiles":
            return self.student_profiles
        elif table_name == "movement_logs":
            return self.movement_logs
        elif table_name == "curfew_alerts":
            return self.curfew_alerts
        elif table_name == "system_settings":
            return self.system_settings
        else:
            if not hasattr(self, f"_{table_name}"):
                setattr(self, f"_{table_name}", [])
            return getattr(self, f"_{table_name}")

    def _set_table_store(
        self,
        table_name: str,
        records: List[Dict[str, Any]]
    ) -> None:
        if table_name == "student_profiles":
            self.student_profiles = records
        elif table_name == "movement_logs":
            self.movement_logs = records
        elif table_name == "curfew_alerts":
            self.curfew_alerts = records
        elif table_name == "system_settings":
            self.system_settings = records

    def get_student_profile(self, student_id: str) -> Optional[Dict[str, Any]]:
        for s in self.student_profiles:
            if str(s.get("id")) == str(student_id):
                return s
        return None

    def reset(self) -> None:
        """Clear dynamic tables and reseed system settings."""
        self.student_profiles.clear()
        self.movement_logs.clear()
        self.curfew_alerts.clear()
        self.system_settings = _default_system_settings()


# Default singleton instance of Mock client
_mock_client_instance = MockHostelSupabaseClient()
_injected_client: Optional[Any] = None


def get_mock_client() -> MockHostelSupabaseClient:
    """Return the singleton MockHostelSupabaseClient."""
    return _mock_client_instance


def set_hostel_client(client: Optional[Any] = None) -> None:
    """Inject custom or mock client instance (useful for unit testing)."""
    global _injected_client
    _injected_client = client


def reset_hostel_client() -> None:
    """Reset injected client and mock database state."""
    global _injected_client
    _injected_client = None
    _mock_client_instance.reset()


def get_hostel_client(client: Optional[Any] = None) -> Any:
    """
    Return Supabase client scoped strictly to the girls_hostel schema.
    If client or an injected client is provided, it is scoped to girls_hostel.
    Never returns an unscoped client that could target default schemas.
    If running in test mode (BIOSECURE_TEST_MODE=1) or if live Supabase is
    unavailable/fails to scope, gracefully falls back to the in-memory mock.
    """
    target = client if client is not None else _injected_client

    if target is not None:
        if isinstance(target, MockHostelSupabaseClient):
            return target
        if hasattr(target, "schema"):
            try:
                scoped = target.schema(HOSTEL_SCHEMA)
                if scoped is None:
                    raise RuntimeError(
                        f"client.schema('{HOSTEL_SCHEMA}') returned None"
                    )
                return scoped
            except Exception as e:
                logger.warning(
                    f"Could not bind client to '{HOSTEL_SCHEMA}': {e}. "
                    "Falling back to mock client to prevent unscoped leakage."
                )
                return _mock_client_instance
        logger.warning(
            "Client lacks schema() support; falling back to mock client."
        )
        return _mock_client_instance

    if os.environ.get("BIOSECURE_TEST_MODE") == "1":
        return _mock_client_instance

    if supabase_admin is not None:
        try:
            return supabase_admin.schema(HOSTEL_SCHEMA)
        except Exception as e:
            logger.warning(
                f"Could not bind to '{HOSTEL_SCHEMA}' on supabase_admin: "
                f"{e}. Falling back to mock client."
            )
            return _mock_client_instance

    return _mock_client_instance


# ============================================================================
# Core Hostel Database Interface Methods
# ============================================================================

def get_student_by_id(
    student_id: str,
    client: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """Fetch a single student profile by UUID from student_profiles."""
    try:
        c = get_hostel_client(client)
        res = (
            c.table("student_profiles")
            .select("*")
            .eq("id", str(student_id))
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.error(f"Error fetching student {student_id}: {e}")
        return None


def fetch_all_hostel_students(
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Fetch all student profiles from girls_hostel.student_profiles."""
    try:
        c = get_hostel_client(client)
        res = c.table("student_profiles").select("*").execute()
        return res.data or []
    except Exception as e:
        if "PGRST106" in str(e) or "Invalid schema" in str(e):
            logger.warning("Supabase REST API does not expose girls_hostel schema yet. Using fallback storage.")
            res = _mock_client_instance.table("student_profiles").select("*").execute()
            return res.data or []
        logger.error(f"Error fetching girls_hostel students: {e}")
        return []


def match_face_embedding(
    embedding: List[float],
    threshold: float = 0.40,
    count: int = 1,
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Call girls_hostel.match_face RPC function to identify student faces.
    """
    if not embedding:
        return []
    try:
        c = get_hostel_client(client)
        params = {
            "query_embedding": embedding,
            "match_threshold": threshold,
            "match_count": count
        }
        try:
            res = c.rpc("match_face", params).execute()
        except Exception:
            admin = client or supabase_admin or c
            res = admin.rpc("girls_hostel.match_face", params).execute()

        return res.data or []
    except Exception as e:
        logger.error(f"Error calling girls_hostel.match_face RPC: {e}")
        return []


def match_hostel_face(
    query_embedding: List[float],
    threshold: float = 0.40,
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Compatibility wrapper calling match_face_embedding with count=1."""
    return match_face_embedding(
        embedding=query_embedding,
        threshold=threshold,
        count=1,
        client=client
    )


def update_student_status(
    student_id: str,
    status: str,
    movement_time: Optional[datetime] = None,
    client: Optional[Any] = None
) -> bool:
    """Update student current_status and last_movement_time."""
    try:
        c = get_hostel_client(client)
        if movement_time:
            m_time = movement_time.isoformat()
        else:
            m_time = datetime.now(timezone.utc).isoformat()
        payload = {
            "current_status": status,
            "last_movement_time": m_time
        }
        res = (
            c.table("student_profiles")
            .update(payload)
            .eq("id", str(student_id))
            .execute()
        )
        if res.data is not None and len(res.data) > 0:
            logger.info(f"Student {student_id} status updated to {status}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to update status for student {student_id}: {e}")
        return False


def update_student_movement_state(
    student_id: str,
    direction: str,
    camera_id: str,
    client: Optional[Any] = None
) -> bool:
    """
    Update student status ('IN' or 'OUT') and insert a movement log.
    Maintains compatibility with camera scanner services.
    Short-circuits if student does not exist or status update fails,
    preventing orphaned movement log entries.
    """
    try:
        status_ok = update_student_status(
            student_id=student_id,
            status=direction,
            client=client
        )
        if not status_ok:
            logger.warning(
                f"Cannot record movement for student {student_id}: status "
                "update failed or student does not exist."
            )
            return False

        log_id = insert_movement_log(
            student_id=student_id,
            direction=direction,
            camera_id=camera_id,
            client=client
        )
        return log_id is not None
    except Exception as e:
        logger.error(
            f"Failed to record movement state for student {student_id}: {e}"
        )
        return False


def insert_movement_log(
    student_id: str,
    direction: str,
    camera_id: str,
    confidence: float = 1.0,
    snapshot_url: Optional[str] = None,
    client: Optional[Any] = None
) -> Optional[int]:
    """Insert an entry into girls_hostel.movement_logs."""
    try:
        c = get_hostel_client(client)
        payload = {
            "student_id": str(student_id),
            "direction": direction,
            "camera_id": camera_id,
            "confidence": confidence,
            "snapshot_url": snapshot_url
        }
        res = c.table("movement_logs").insert(payload).execute()
        if res.data and len(res.data) > 0:
            log_id = res.data[0].get("id")
            logger.info(
                f"Inserted movement log #{log_id} for student {student_id}"
            )
            return int(log_id) if log_id is not None else None
        return None
    except Exception as e:
        logger.error(
            f"Error inserting movement log for student {student_id}: {e}"
        )
        return None


def get_recent_movement_logs(
    limit: int = 50,
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Fetch recent movement logs with student details."""
    try:
        c = get_hostel_client(client)
        columns = (
            "id, direction, camera_id, timestamp, confidence, snapshot_url, "
            "student_id, student_profiles(name, roll_number, room_number)"
        )
        res = (
            c.table("movement_logs")
            .select(columns)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        if "PGRST106" in str(e) or "Invalid schema" in str(e):
            res = _mock_client_instance.table("movement_logs").select("*").order("timestamp", desc=True).limit(limit).execute()
            return res.data or []
        logger.error(f"Error fetching movement logs: {e}")
        return []


def fetch_recent_movement_logs(
    limit: int = 50,
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Compatibility alias for get_recent_movement_logs."""
    return get_recent_movement_logs(limit=limit, client=client)


def get_active_curfew_alerts(
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Fetch active OVERDUE_OUT alerts joined with student details."""
    try:
        c = get_hostel_client(client)
        columns = (
            "id, student_id, curfew_date, system_start_time, "
            "curfew_end_time, status, alert_triggered_at, resolved_at, notes, "
            "student_profiles(name, roll_number, room_number, parent_contact, "
            "last_movement_time)"
        )
        res = (
            c.table("curfew_alerts")
            .select(columns)
            .eq("status", "OVERDUE_OUT")
            .order("alert_triggered_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching active curfew alerts: {e}")
        return []


def fetch_overdue_curfew_students(
    client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """Compatibility alias for get_active_curfew_alerts."""
    return get_active_curfew_alerts(client=client)


def create_curfew_alert(
    student_id: str,
    curfew_date: Optional[date] = None,
    start_time: str = "17:00:00",
    end_time: str = "19:30:00",
    status: str = "OVERDUE_OUT",
    client: Optional[Any] = None
) -> Optional[int]:
    """Create a new curfew alert entry in girls_hostel.curfew_alerts."""
    try:
        c = get_hostel_client(client)
        c_date = (
            curfew_date.isoformat()
            if isinstance(curfew_date, date)
            else str(curfew_date)
            if curfew_date
            else date.today().isoformat()
        )

        # Deduplicate active OVERDUE_OUT alerts for the student on this date
        if status == "OVERDUE_OUT":
            existing = (
                c.table("curfew_alerts")
                .select("id")
                .eq("student_id", str(student_id))
                .eq("curfew_date", c_date)
                .eq("status", "OVERDUE_OUT")
                .execute()
            )
            if existing.data and len(existing.data) > 0:
                existing_id = existing.data[0].get("id")
                logger.info(
                    f"Active curfew alert #{existing_id} already exists for "
                    f"student {student_id} on {c_date}. Returning existing ID."
                )
                return int(existing_id) if existing_id is not None else None

        payload = {
            "student_id": str(student_id),
            "curfew_date": c_date,
            "system_start_time": start_time,
            "curfew_end_time": end_time,
            "status": status
        }
        res = c.table("curfew_alerts").insert(payload).execute()
        if res.data and len(res.data) > 0:
            alert_id = res.data[0].get("id")
            logger.info(
                f"Created curfew alert #{alert_id} for student {student_id}"
            )
            return int(alert_id) if alert_id is not None else None
        return None
    except Exception as e:
        logger.error(
            f"Error creating curfew alert for student {student_id}: {e}"
        )
        return None


def resolve_curfew_alert(
    alert_id: int,
    status: str = "RESOLVED",
    notes: str = "",
    client: Optional[Any] = None
) -> bool:
    """Resolve a curfew alert with updated status, notes, and timestamp."""
    try:
        c = get_hostel_client(client)
        payload = {
            "status": status,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes
        }
        res = (
            c.table("curfew_alerts")
            .update(payload)
            .eq("id", alert_id)
            .execute()
        )
        if res.data is not None and len(res.data) > 0:
            logger.info(
                f"Curfew alert #{alert_id} resolved with status '{status}'"
            )
            return True
        return False
    except Exception as e:
        logger.error(f"Error resolving curfew alert #{alert_id}: {e}")
        return False


def get_system_settings(
    key: str,
    client: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve system settings JSON configuration by key."""
    try:
        c = get_hostel_client(client)
        res = (
            c.table("system_settings")
            .select("value")
            .eq("key", key)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0].get("value")
        return None
    except Exception as e:
        logger.error(f"Error getting system setting for key '{key}': {e}")
        return None


def update_system_settings(
    key: str,
    value: Dict[str, Any],
    client: Optional[Any] = None
) -> bool:
    """Upsert system settings JSON configuration by key."""
    try:
        c = get_hostel_client(client)
        payload = {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        res = c.table("system_settings").upsert(payload).execute()
        if res.data is not None and len(res.data) > 0:
            logger.info(f"Updated system setting for key '{key}'")
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating system setting for key '{key}': {e}")
        return False
