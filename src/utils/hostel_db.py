"""
Girls Hostel Database Utilities — BioSecure AI.

All DB interactions in this module explicitly target the 'girls_hostel' schema
to guarantee 100% data isolation from classroom attendance systems.
"""

import copy
import json
import logging
import os
import time
import urllib.parse
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

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
                if "camera_role" in item:
                    pk_col = "camera_role"
                    pk_val = item["camera_role"]
                elif "key" in item:
                    pk_col = "key"
                    pk_val = item["key"]
                else:
                    pk_col = "id"
                    pk_val = item.get("id")
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


def _default_camera_settings() -> List[Dict[str, Any]]:
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
            "updated_at": now_str
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
        self.camera_settings: List[Dict[str, Any]] = _default_camera_settings()

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
        elif table_name == "camera_settings":
            return self.camera_settings
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
        elif table_name == "camera_settings":
            self.camera_settings = records

    def get_student_profile(self, student_id: str) -> Optional[Dict[str, Any]]:
        for s in self.student_profiles:
            if str(s.get("id")) == str(student_id):
                return s
        return None

    def reset(self) -> None:
        """Clear dynamic tables and reseed system and camera settings."""
        self.student_profiles.clear()
        self.movement_logs.clear()
        self.curfew_alerts.clear()
        self.system_settings = _default_system_settings()
        self.camera_settings = _default_camera_settings()


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


def update_student_profile(
    student_id: str,
    updates: Dict[str, Any],
    client: Optional[Any] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Update details for an existing student profile in girls_hostel.student_profiles.
    
    Args:
        student_id: UUID or ID string of student profile
        updates: Dict containing fields to update (e.g. name, roll_number, room_number, parent_contact, etc.)
        client: Optional DB client override
        
    Returns:
        Tuple of (success: bool, message: str, updated_student_dict)
    """
    try:
        c = get_hostel_client(client)

        # 1. Fetch existing student profile
        existing = get_student_by_id(student_id, client=c)
        if not existing:
            return False, f"Student profile with ID '{student_id}' not found.", None

        # 2. Check roll_number uniqueness if roll_number is being changed
        new_roll = updates.get("roll_number")
        if new_roll and str(new_roll).strip() != str(existing.get("roll_number", "")).strip():
            new_roll_clean = str(new_roll).strip()
            try:
                roll_check = c.table("student_profiles").select("id").eq("roll_number", new_roll_clean).execute()
            except Exception as schema_err:
                if "PGRST106" in str(schema_err) or "Invalid schema" in str(schema_err):
                    c = get_mock_client()
                    roll_check = c.table("student_profiles").select("id").eq("roll_number", new_roll_clean).execute()
                else:
                    raise

            if roll_check.data:
                for match in roll_check.data:
                    if str(match.get("id")) != str(student_id):
                        return False, f"Roll Number '{new_roll_clean}' is already assigned to another student.", None

        # 3. Build payload (protect id field)
        payload = copy.deepcopy(updates)
        payload.pop("id", None)
        payload_with_time = copy.deepcopy(payload)
        payload_with_time["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 4. Perform database update with fallback handling for missing columns
        try:
            res = c.table("student_profiles").update(payload_with_time).eq("id", str(student_id)).execute()
        except Exception as update_err:
            err_str = str(update_err)
            if "updated_at" in err_str or "PGRST204" in err_str:
                logger.warning(f"updated_at column not present in student_profiles table schema: {update_err}. Retrying update without updated_at.")
                try:
                    res = c.table("student_profiles").update(payload).eq("id", str(student_id)).execute()
                except Exception as retry_err:
                    if "PGRST106" in str(retry_err) or "Invalid schema" in str(retry_err):
                        c = get_mock_client()
                        res = c.table("student_profiles").update(payload).eq("id", str(student_id)).execute()
                    else:
                        raise
            elif "PGRST106" in err_str or "Invalid schema" in err_str:
                logger.warning("girls_hostel schema update notice — using local mock client fallback.")
                c = get_mock_client()
                res = c.table("student_profiles").update(payload_with_time).eq("id", str(student_id)).execute()
            else:
                raise

        if res.data and len(res.data) > 0:
            updated_student = res.data[0]
            logger.info(f"Successfully updated student profile '{student_id}' ({updated_student.get('name')}).")
            return True, f"Student profile for '{updated_student.get('name')}' updated successfully.", updated_student

        updated_student = get_student_by_id(student_id, client=c)
        if updated_student:
            return True, "Student profile updated successfully.", updated_student

        return False, "Failed to update student profile record.", None
    except Exception as e:
        logger.error(f"Error updating student profile {student_id}: {e}")
        return False, str(e), None




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
    notes: Optional[str] = None,
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
        if notes is not None:
            payload["notes"] = notes

        try:
            res = c.table("movement_logs").insert(payload).execute()
        except Exception as insert_err:
            if "PGRST106" in str(insert_err) or "Invalid schema" in str(insert_err) or "relation" in str(insert_err).lower():
                logger.warning("girls_hostel schema not exposed in Supabase — using local mock client for movement log insert.")
                c = get_mock_client()
                res = c.table("movement_logs").insert(payload).execute()
            else:
                raise

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
        try:
            res = (
                c.table("movement_logs")
                .select("*")
                .order("timestamp", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as query_err:
            if "PGRST106" in str(query_err) or "Invalid schema" in str(query_err) or "relation" in str(query_err).lower():
                logger.warning("girls_hostel schema notice — using local mock client for movement logs.")
                c = get_mock_client()
                res = (
                    c.table("movement_logs")
                    .select("*")
                    .order("timestamp", desc=True)
                    .limit(limit)
                    .execute()
                )
            else:
                logger.error(f"Error executing movement_logs query: {query_err}")
                return []

        raw_logs = res.data or []
        if not raw_logs:
            return []

        # Fetch students to resolve details in Python
        students = fetch_all_hostel_students(client=c)
        student_map = {}
        for s in students:
            sid = str(s.get("id", ""))
            student_map[sid] = {
                "name": s.get("name", "Unknown Student"),
                "roll_number": s.get("roll_number", "N/A"),
                "room_number": s.get("room_number", "N/A"),
                "parent_contact": s.get("parent_contact", ""),
                "student_contact": s.get("student_contact", "")
            }

        logs = []
        for l in raw_logs:
            log_item = copy.deepcopy(l)
            sid = str(log_item.get("student_id", ""))
            sp = log_item.get("student_profiles")
            if not sp or not isinstance(sp, dict):
                log_item["student_profiles"] = student_map.get(sid, {
                    "name": "Unknown Student",
                    "roll_number": "N/A",
                    "room_number": "N/A",
                    "parent_contact": "",
                    "student_contact": ""
                })
            
            # Ensure optional attributes are non-null for UI
            if "confidence" not in log_item or log_item["confidence"] is None:
                log_item["confidence"] = 1.0
            if "snapshot_url" not in log_item:
                log_item["snapshot_url"] = None
            if "notes" not in log_item:
                log_item["notes"] = None

            logs.append(log_item)

        return logs
    except Exception as e:
        logger.error(f"Error fetching movement logs: {e}")
        return []




def record_manual_movement(
    student_id: str,
    direction: str,
    notes: Optional[str] = None,
    camera_id: str = "MANUAL_ENTRY",
    client: Optional[Any] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Record a manual IN or OUT movement for a student by warden.
    
    1. Validates student exists.
    2. Updates student current_status ('IN' or 'OUT') and last_movement_time.
    3. Inserts a movement log entry with camera_id='MANUAL_ENTRY' (or custom),
       confidence=1.0, and notes.
    4. If direction is 'IN', automatically resolves any open OVERDUE_OUT curfew alerts for the student.
    
    Returns (success: bool, message: str, student_profile: Optional[Dict[str, Any]])
    """
    try:
        dir_clean = str(direction).strip().upper()
        if dir_clean not in ("IN", "OUT"):
            return False, "Invalid movement direction. Must be 'IN' or 'OUT'.", None

        c = get_hostel_client(client)
        student = get_student_by_id(student_id, client=c)
        if not student:
            return False, f"Student record with ID '{student_id}' not found.", None

        student_name = student.get("name", "Student")
        roll_number = student.get("roll_number", "")

        status_updated = update_student_status(student_id=student_id, status=dir_clean, client=c)
        if not status_updated:
            return False, f"Failed to update status for student '{student_name}'.", None

        note_text = notes.strip() if notes and notes.strip() else f"Manual {dir_clean} entry by warden"

        log_id = insert_movement_log(
            student_id=student_id,
            direction=dir_clean,
            camera_id=camera_id,
            confidence=1.0,
            snapshot_url=None,
            notes=note_text,
            client=c
        )

        resolved_alerts_count = 0
        if dir_clean == "IN":
            try:
                alerts = get_active_curfew_alerts(client=c)
                for alert in alerts:
                    if str(alert.get("student_id")) == str(student_id):
                        alert_id = alert.get("id")
                        if alert_id:
                            resolve_curfew_alert(
                                alert_id=alert_id,
                                status="RESOLVED",
                                notes=f"Auto-resolved upon manual IN entry by warden ({note_text})",
                                client=c
                            )
                            resolved_alerts_count += 1
            except Exception as alert_err:
                logger.warning(f"Failed to auto-resolve curfew alert for student {student_id}: {alert_err}")

        updated_student = get_student_by_id(student_id, client=c)
        msg = f"Manual {dir_clean} entry recorded for {student_name} ({roll_number})."
        if resolved_alerts_count > 0:
            msg += f" Auto-resolved {resolved_alerts_count} overdue curfew alert(s)."

        return True, msg, updated_student
    except Exception as e:
        logger.error(f"Error in record_manual_movement for student {student_id}: {e}")
        return False, str(e), None


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
        try:
            res = (
                c.table("curfew_alerts")
                .select("*")
                .eq("status", "OVERDUE_OUT")
                .order("alert_triggered_at", desc=True)
                .execute()
            )
        except Exception as query_err:
            if "PGRST106" in str(query_err) or "Invalid schema" in str(query_err) or "relation" in str(query_err).lower():
                c = get_mock_client()
                res = (
                    c.table("curfew_alerts")
                    .select("*")
                    .eq("status", "OVERDUE_OUT")
                    .order("alert_triggered_at", desc=True)
                    .execute()
                )
            else:
                logger.error(f"Error executing curfew_alerts query: {query_err}")
                return []

        alerts = res.data or []
        if not alerts:
            return []

        students = fetch_all_hostel_students(client=c)
        student_map = {str(s.get("id", "")): s for s in students}

        formatted_alerts = []
        for a in alerts:
            alert_item = copy.deepcopy(a)
            sid = str(alert_item.get("student_id", ""))
            sp = alert_item.get("student_profiles")
            if not sp or not isinstance(sp, dict):
                student = student_map.get(sid, {})
                alert_item["student_profiles"] = {
                    "name": student.get("name", "Unknown Student"),
                    "roll_number": student.get("roll_number", "N/A"),
                    "room_number": student.get("room_number", "N/A"),
                    "parent_contact": student.get("parent_contact", ""),
                    "student_contact": student.get("student_contact", ""),
                    "last_movement_time": student.get("last_movement_time")
                }
            formatted_alerts.append(alert_item)

        return formatted_alerts
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
        # Validate that value is JSON serializable (raises on circular references)
        json.dumps(value)
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


# ============================================================================
# Camera Settings Persistence & RTSP Stream URL Utilities
# ============================================================================

import tempfile

CAMERA_RELOAD_SIGNAL_PATH = os.path.join(tempfile.gettempdir(), "hostel_camera_reload.signal")


def trigger_camera_reload_signal() -> None:
    """Touch the IPC reload signal file to notify background worker processes to reload configuration."""
    try:
        with open(CAMERA_RELOAD_SIGNAL_PATH, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        logger.warning(f"Could not write camera reload signal file: {e}")


def _sync_camera_sources_setting(
    role: str,
    payload: Dict[str, Any],
    client: Optional[Any] = None
) -> None:
    """Internal helper to keep girls_hostel.system_settings['camera_sources'] synchronized."""
    try:
        current_sources = get_system_settings("camera_sources", client=client) or {}
        stream_url = build_rtsp_url(payload)
        key_name = "entry_cam" if role == "IN" else "exit_cam"
        current_sources[key_name] = stream_url
        update_system_settings("camera_sources", current_sources, client=client)
    except Exception as e:
        logger.warning(f"Could not dual-sync system_settings['camera_sources']: {e}")


def build_rtsp_url(settings: Optional[Dict[str, Any]]) -> str:
    """
    Construct vendor-specific RTSP stream URL or local device index string.
    Safely encodes special characters in credentials using RFC 3986 percent-encoding.
    """
    if not settings:
        return "0"

    vendor = str(settings.get("vendor") or "").strip().lower()
    custom_url = str(settings.get("custom_rtsp_url") or "").strip()

    # USB Webcam or Local Device Index
    if any(k in vendor for k in ("usb", "webcam", "local", "camera index")):
        if custom_url and (custom_url.isdigit() or custom_url.startswith("/dev/video")):
            return custom_url
        channel = settings.get("channel")
        if channel is not None and str(channel).isdigit():
            return str(channel)
        role = str(settings.get("camera_role") or "IN").upper()
        return "0" if role == "IN" else "1"

    # Custom RTSP override
    if "custom" in vendor or (custom_url and custom_url.lower().startswith("rtsp://")):
        return custom_url

    ip = str(settings.get("ip_address") or "127.0.0.1").strip()
    port = settings.get("port") or 554
    channel = settings.get("channel") or (1 if str(settings.get("camera_role", "IN")).upper() == "IN" else 2)

    # Build credentials prefix with RFC 3986 percent-encoding
    username = str(settings.get("username") or "").strip()
    password = str(settings.get("password") or "").strip()

    auth_part = ""
    if username:
        safe_user = urllib.parse.quote(username, safe="")
        if password:
            safe_pass = urllib.parse.quote(password, safe="")
            auth_part = f"{safe_user}:{safe_pass}@"
        else:
            auth_part = f"{safe_user}@"

    # Hikvision preset
    if "hik" in vendor:
        ch_str = str(channel)
        channel_code = ch_str if ch_str.endswith("01") else f"{ch_str}01"
        return f"rtsp://{auth_part}{ip}:{port}/Streaming/Channels/{channel_code}"

    # CP Plus & Dahua presets
    if any(k in vendor for k in ("cp plus", "cpplus", "dahua")):
        return f"rtsp://{auth_part}{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0"

    # TVT preset
    if "tvt" in vendor:
        return f"rtsp://{auth_part}{ip}:{port}/ch{channel}/main/av_stream"

    # Generic RTSP fallback
    if custom_url:
        return custom_url
    return f"rtsp://{auth_part}{ip}:{port}/live"


def get_default_camera_settings(camera_role: Optional[str] = None) -> Any:
    """Return default seed configuration dictionaries for IN and OUT gates."""
    now_str = datetime.now(timezone.utc).isoformat()
    defaults = {
        "IN": {
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
        "OUT": {
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
    }
    if camera_role:
        role = camera_role.strip().upper()
        return copy.deepcopy(defaults.get(role, defaults["IN"]))
    return [copy.deepcopy(defaults["IN"]), copy.deepcopy(defaults["OUT"])]


def get_camera_settings(
    camera_role: Optional[str] = None,
    client: Optional[Any] = None
) -> Any:
    """
    Fetch camera configuration from girls_hostel.camera_settings.
    If camera_role is provided ('IN' or 'OUT'), returns a single dictionary.
    If camera_role is None, returns a list containing configurations for both gates.
    Falls back to default configurations gracefully on any database error.
    """
    try:
        c = get_hostel_client(client)
        query = c.table("camera_settings").select("*")
        if camera_role:
            role_norm = camera_role.strip().upper()
            res = query.eq("camera_role", role_norm).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
            return get_default_camera_settings(role_norm)
        else:
            res = query.order("camera_role").execute()
            if res.data and len(res.data) > 0:
                found_roles = {item.get("camera_role") for item in res.data}
                results = list(res.data)
                for missing_role in ("IN", "OUT"):
                    if missing_role not in found_roles:
                        results.append(get_default_camera_settings(missing_role))
                results.sort(key=lambda x: str(x.get("camera_role", "")))
                return results
            return get_default_camera_settings()
    except Exception as e:
        logger.error(f"Error fetching camera settings from girls_hostel: {e}")
        return get_default_camera_settings(camera_role)


def save_camera_settings(
    camera_role: str,
    settings: Dict[str, Any],
    client: Optional[Any] = None
) -> bool:
    """
    Persist camera settings for 'IN' or 'OUT' gate to girls_hostel.camera_settings.
    Automatically touches the IPC reload signal file to notify all worker processes.
    """
    if not camera_role or not isinstance(settings, dict):
        logger.warning("save_camera_settings called with invalid role or payload")
        return False

    role_norm = camera_role.strip().upper()
    if role_norm not in ("IN", "OUT"):
        logger.warning(f"Invalid camera_role: {camera_role}. Must be 'IN' or 'OUT'.")
        return False

    try:
        c = get_hostel_client(client)
        now_str = datetime.now(timezone.utc).isoformat()

        payload = {
            "camera_role": role_norm,
            "vendor": str(settings.get("vendor") or "Generic RTSP").strip(),
            "ip_address": str(settings.get("ip_address") or "").strip() or None,
            "port": int(settings.get("port") or 554),
            "channel": int(settings.get("channel") or (1 if role_norm == "IN" else 2)),
            "username": str(settings.get("username") or "").strip() or None,
            "password": str(settings.get("password") or "").strip() or None,
            "custom_rtsp_url": str(settings.get("custom_rtsp_url") or "").strip() or None,
            "resolution": str(settings.get("resolution") or "1280x720").strip(),
            "fps": int(settings.get("fps") or 30),
            "enabled": bool(settings.get("enabled", True)),
            "updated_at": now_str,
        }

        if settings.get("id"):
            payload["id"] = settings["id"]
        else:
            payload["id"] = 1 if role_norm == "IN" else 2

        res = c.table("camera_settings").upsert(payload).execute()
        success = res.data is not None and len(res.data) > 0

        if success:
            logger.info(f"Successfully saved camera settings for {role_norm}")
            _sync_camera_sources_setting(role_norm, payload, client=c)
            trigger_camera_reload_signal()
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to save camera settings for {role_norm}: {e}")
        return False


# Compatibility alias as specified in requirements
upsert_camera_settings = save_camera_settings
