"""
Unit Tests for Milestone 1: Schema Isolation & Girls Hostel Database Layer.

Validates:
1. SQL DDL syntax, schema, tables, RLS, policies, HNSW index, RPC function.
2. Schema Isolation & Zero-Leakage (zero public schema references).
3. Functional unit tests for all hostel_db interface functions & edge cases.
"""

import os
import re
import unittest
from datetime import date, datetime, timezone

from src.utils.hostel_db import (
    HOSTEL_SCHEMA,
    MockHostelSupabaseClient,
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


class TestSchemaDDLSyntaxAndCompleteness(unittest.TestCase):
    """Test 1: SQL DDL syntax and completeness validation."""

    @classmethod
    def setUpClass(cls):
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "scripts",
            "girls_hostel_schema.sql"
        )
        cls.schema_path = os.path.abspath(schema_path)
        with open(cls.schema_path, "r", encoding="utf-8") as f:
            cls.sql_content = f.read()

    def test_schema_file_exists_and_not_empty(self):
        self.assertTrue(
            os.path.exists(self.schema_path),
            f"Schema file not found at {self.schema_path}"
        )
        self.assertGreater(len(self.sql_content), 100)

    def test_schema_definition_present(self):
        pattern = r"CREATE\s+SCHEMA\s+(IF\s+NOT\s+EXISTS\s+)?girls_hostel\s*;"
        self.assertRegex(
            self.sql_content,
            pattern,
            "CREATE SCHEMA statement missing or malformed."
        )

    def test_creation_of_all_four_tables(self):
        expected_tables = [
            "girls_hostel.student_profiles",
            "girls_hostel.movement_logs",
            "girls_hostel.curfew_alerts",
            "girls_hostel.system_settings",
        ]
        for table in expected_tables:
            p = rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?{re.escape(table)}"
            self.assertRegex(
                self.sql_content,
                p,
                f"Table {table} creation statement is missing."
            )

    def test_student_profiles_columns(self):
        required_elements = [
            "id UUID PRIMARY KEY",
            "name VARCHAR(255) NOT NULL",
            "roll_number VARCHAR(100) UNIQUE NOT NULL",
            "room_number VARCHAR(50) NOT NULL",
            "embedding VECTOR(512)",
            "current_status VARCHAR(20) DEFAULT 'IN'",
            "last_movement_time TIMESTAMP WITH TIME ZONE",
        ]
        for elem in required_elements:
            self.assertIn(
                elem,
                self.sql_content,
                f"Missing column '{elem}' in student_profiles."
            )

    def test_movement_logs_foreign_key_and_cascade(self):
        fk = "REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE"
        self.assertIn(fk, self.sql_content)
        self.assertIn("direction VARCHAR(10) NOT NULL", self.sql_content)
        self.assertIn("camera_id VARCHAR(50) NOT NULL", self.sql_content)

    def test_curfew_alerts_columns(self):
        self.assertIn(
            "curfew_date DATE DEFAULT CURRENT_DATE", self.sql_content
        )
        self.assertIn(
            "system_start_time TIME DEFAULT '17:00:00'", self.sql_content
        )
        self.assertIn(
            "curfew_end_time TIME DEFAULT '19:30:00'", self.sql_content
        )
        self.assertIn(
            "status VARCHAR(30) DEFAULT 'OVERDUE_OUT'", self.sql_content
        )

    def test_row_level_security_enabled_on_all_four_tables(self):
        expected_rls_tables = [
            "girls_hostel.student_profiles",
            "girls_hostel.movement_logs",
            "girls_hostel.curfew_alerts",
            "girls_hostel.system_settings",
        ]
        for table in expected_rls_tables:
            pattern = (
                rf"ALTER\s+TABLE\s+{re.escape(table)}\s+ENABLE\s+ROW\s+"
                r"LEVEL\s+SECURITY\s*;"
            )
            self.assertRegex(
                self.sql_content,
                pattern,
                f"RLS is not enabled on {table}!"
            )

    def test_service_role_policies_defined(self):
        expected_policies = [
            "service_role_all_student_profiles",
            "service_role_all_movement_logs",
            "service_role_all_curfew_alerts",
            "service_role_all_system_settings",
        ]
        for policy in expected_policies:
            pattern = rf"CREATE\s+POLICY\s+{policy}\s+ON\s+girls_hostel\."
            self.assertRegex(
                self.sql_content,
                pattern,
                f"Policy {policy} is missing in SQL migration script."
            )
            self.assertIn("TO service_role", self.sql_content)

    def test_hnsw_vector_index_present(self):
        pattern = (
            r"CREATE\s+INDEX\s+(IF\s+NOT\s+EXISTS\s+)?"
            r"idx_girls_hostel_students_embedding\s+"
            r"ON\s+girls_hostel\.student_profiles\s+USING\s+hnsw\s*\(\s*"
            r"embedding\s+vector_cosine_ops\s*\)\s*;"
        )
        self.assertRegex(
            self.sql_content,
            pattern,
            "HNSW vector cosine index statement missing or invalid."
        )

    def test_curfew_alerts_active_unique_index_present(self):
        pattern = (
            r"CREATE\s+UNIQUE\s+INDEX\s+(IF\s+NOT\s+EXISTS\s+)?"
            r"idx_girls_hostel_curfew_active_uniq\s+"
            r"ON\s+girls_hostel\.curfew_alerts\s*\(\s*student_id,\s*"
            r"curfew_date\s*\)\s+"
            r"WHERE\s+status\s*=\s*'OVERDUE_OUT'\s*;"
        )
        self.assertRegex(
            self.sql_content,
            pattern,
            "Partial unique index idx_girls_hostel_curfew_active_uniq missing."
        )

    def test_match_face_rpc_function_signature(self):
        self.assertIn(
            "CREATE OR REPLACE FUNCTION girls_hostel.match_face(",
            self.sql_content
        )
        self.assertIn("query_embedding VECTOR(512)", self.sql_content)
        self.assertIn("match_threshold FLOAT DEFAULT 0.40", self.sql_content)
        self.assertIn("match_count INT DEFAULT 1", self.sql_content)
        self.assertIn("SECURITY DEFINER", self.sql_content)
        self.assertIn(
            "SET search_path = girls_hostel, pg_temp;",
            self.sql_content
        )
        self.assertIn(
            "1 - (sp.embedding <=> query_embedding) AS similarity",
            self.sql_content
        )

    def test_match_face_rpc_search_path_pinned(self):
        pattern = (
            r"SECURITY\s+DEFINER\s*\n\s*"
            r"SET\s+search_path\s*=\s*girls_hostel,\s*pg_temp;\s*\n\s*"
            r"AS\s+\$\$"
        )
        self.assertRegex(
            self.sql_content,
            pattern,
            "match_face RPC function must set search_path right above AS $$"
        )

    def test_default_system_settings_inserted(self):
        self.assertIn("curfew_schedule", self.sql_content)
        self.assertIn("camera_sources", self.sql_content)
        self.assertIn("alert_config", self.sql_content)
        self.assertIn("ON CONFLICT (key) DO NOTHING", self.sql_content)

    def test_grants_to_service_role(self):
        self.assertIn(
            "GRANT ALL ON SCHEMA girls_hostel TO service_role;",
            self.sql_content
        )
        self.assertIn(
            "GRANT ALL ON ALL TABLES IN SCHEMA girls_hostel TO service_role;",
            self.sql_content
        )
        self.assertIn(
            "GRANT ALL ON ALL FUNCTIONS IN SCHEMA girls_hostel TO "
            "service_role;",
            self.sql_content
        )
        self.assertIn(
            "GRANT ALL ON ALL SEQUENCES IN SCHEMA girls_hostel TO "
            "service_role;",
            self.sql_content
        )


class TestSchemaIsolationAndZeroLeakage(unittest.TestCase):
    """Test 2: Schema Isolation & Zero-Leakage across modules."""

    @classmethod
    def setUpClass(cls):
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "scripts",
            "girls_hostel_schema.sql"
        )
        with open(os.path.abspath(schema_path), "r", encoding="utf-8") as f:
            cls.sql_content = f.read()

        db_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "utils",
            "hostel_db.py"
        )
        with open(os.path.abspath(db_path), "r", encoding="utf-8") as f:
            cls.py_content = f.read()

    def test_sql_schema_zero_public_references(self):
        forbidden_patterns = [
            r"\bpublic\.",
            r"\bpublic\b",
            r"\battendance_logs\b",
        ]
        for pattern in forbidden_patterns:
            matches = re.findall(
                pattern, self.sql_content, flags=re.IGNORECASE
            )
            self.assertEqual(
                matches,
                [],
                f"Forbidden pattern '{pattern}' in SQL: {matches}"
            )

    def test_hostel_db_zero_public_references(self):
        forbidden_patterns = [
            r"\bpublic\.",
            r"\bpublic\b",
            r"\battendance_logs\b",
        ]
        for pattern in forbidden_patterns:
            matches = re.findall(
                pattern, self.py_content, flags=re.IGNORECASE
            )
            self.assertEqual(
                matches,
                [],
                f"Forbidden pattern '{pattern}' in hostel_db.py: {matches}"
            )

    def test_hostel_schema_constant(self):
        self.assertEqual(HOSTEL_SCHEMA, "girls_hostel")


class TestHostelDBFunctionalAndEdgeCases(unittest.TestCase):
    """Test 3: Functional Unit Tests for hostel_db.py with Mock Client."""

    def setUp(self):
        reset_hostel_client()
        self.mock_client = MockHostelSupabaseClient()
        set_hostel_client(self.mock_client)

        # Seed sample student
        self.test_student = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Priya Sharma",
            "roll_number": "2024-GH-0101",
            "room_number": "A-102",
            "hostel_block": "Block-A",
            "parent_contact": "+919876543210",
            "student_contact": "+919876543211",
            "embedding": [0.1] * 512,
            "current_status": "IN",
            "last_movement_time": None,
        }
        self.mock_client.student_profiles.append(self.test_student)

    def tearDown(self):
        reset_hostel_client()

    def test_fetch_all_hostel_students_populated(self):
        students = fetch_all_hostel_students()
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0]["name"], "Priya Sharma")
        self.assertEqual(students[0]["roll_number"], "2024-GH-0101")

    def test_fetch_all_hostel_students_empty(self):
        self.mock_client.student_profiles.clear()
        students = fetch_all_hostel_students()
        self.assertEqual(students, [])

    def test_get_student_by_id_found(self):
        student = get_student_by_id("11111111-1111-1111-1111-111111111111")
        self.assertIsNotNone(student)
        self.assertEqual(student["name"], "Priya Sharma")
        self.assertEqual(student["room_number"], "A-102")

    def test_get_student_by_id_not_found(self):
        student = get_student_by_id("99999999-9999-9999-9999-999999999999")
        self.assertIsNone(student)

    def test_update_student_status_success(self):
        now = datetime.now(timezone.utc)
        success = update_student_status(
            "11111111-1111-1111-1111-111111111111",
            "OUT",
            movement_time=now
        )
        self.assertTrue(success)

        updated = get_student_by_id("11111111-1111-1111-1111-111111111111")
        self.assertEqual(updated["current_status"], "OUT")
        self.assertEqual(updated["last_movement_time"], now.isoformat())

    def test_update_student_status_non_existent(self):
        success = update_student_status("non-existent-id", "OUT")
        self.assertFalse(success)

    def test_insert_movement_log_and_fetch_recent(self):
        log_id = insert_movement_log(
            student_id="11111111-1111-1111-1111-111111111111",
            direction="OUT",
            camera_id="CAM_02_EXIT",
            confidence=0.98,
            snapshot_url="/snapshots/out_001.jpg"
        )
        self.assertIsNotNone(log_id)
        self.assertIsInstance(log_id, int)

        logs = get_recent_movement_logs(limit=10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["direction"], "OUT")
        self.assertEqual(logs[0]["camera_id"], "CAM_02_EXIT")
        self.assertIn("student_profiles", logs[0])
        self.assertEqual(logs[0]["student_profiles"]["name"], "Priya Sharma")

        # Test compatibility alias
        alias_logs = fetch_recent_movement_logs(limit=10)
        self.assertEqual(len(alias_logs), 1)
        self.assertEqual(alias_logs[0]["id"], logs[0]["id"])

    def test_update_student_movement_state_atomic(self):
        success = update_student_movement_state(
            student_id="11111111-1111-1111-1111-111111111111",
            direction="OUT",
            camera_id="CAM_02_EXIT"
        )
        self.assertTrue(success)

        # Check student status
        student = get_student_by_id("11111111-1111-1111-1111-111111111111")
        self.assertEqual(student["current_status"], "OUT")

        # Check movement log created
        logs = get_recent_movement_logs(limit=5)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["direction"], "OUT")
        self.assertEqual(logs[0]["camera_id"], "CAM_02_EXIT")

    def test_update_student_movement_state_non_existent_student(self):
        self.mock_client.movement_logs.clear()
        bad_id = "00000000-0000-0000-0000-000000000000"
        success = update_student_movement_state(
            student_id=bad_id,
            direction="OUT",
            camera_id="CAM_02_EXIT"
        )
        self.assertFalse(success)
        self.assertEqual(len(self.mock_client.movement_logs), 0)

    def test_create_and_resolve_curfew_alert(self):
        today = date.today()
        alert_id = create_curfew_alert(
            student_id="11111111-1111-1111-1111-111111111111",
            curfew_date=today,
            start_time="17:00:00",
            end_time="19:30:00",
            status="OVERDUE_OUT"
        )
        self.assertIsNotNone(alert_id)
        self.assertIsInstance(alert_id, int)

        active = get_active_curfew_alerts()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], alert_id)
        self.assertEqual(active[0]["status"], "OVERDUE_OUT")
        self.assertEqual(active[0]["student_profiles"]["name"], "Priya Sharma")

        # Test compatibility alias
        overdue_compat = fetch_overdue_curfew_students()
        self.assertEqual(len(overdue_compat), 1)
        self.assertEqual(overdue_compat[0]["id"], alert_id)

        # Resolve alert
        resolved = resolve_curfew_alert(
            alert_id=alert_id,
            status="RESOLVED",
            notes="Returned safely at 20:05"
        )
        self.assertTrue(resolved)

        active_after = get_active_curfew_alerts()
        self.assertEqual(len(active_after), 0)

    def test_create_curfew_alert_deduplication(self):
        today = date.today()
        student_id = self.test_student["id"]

        # First alert creation
        alert_id_1 = create_curfew_alert(
            student_id=student_id,
            curfew_date=today,
            status="OVERDUE_OUT"
        )
        self.assertIsNotNone(alert_id_1)
        self.assertEqual(len(self.mock_client.curfew_alerts), 1)

        # Duplicate alert attempt on same student, date, and status
        alert_id_2 = create_curfew_alert(
            student_id=student_id,
            curfew_date=today,
            status="OVERDUE_OUT"
        )
        self.assertEqual(alert_id_1, alert_id_2)
        # Verify no duplicate alert row was added
        self.assertEqual(len(self.mock_client.curfew_alerts), 1)

        # Direct table insert with duplicate active alert raises ValueError
        with self.assertRaises(ValueError):
            self.mock_client.table("curfew_alerts").insert({
                "student_id": student_id,
                "curfew_date": today.isoformat(),
                "status": "OVERDUE_OUT"
            }).execute()

        # If existing alert is resolved, new alert can be created
        resolved = resolve_curfew_alert(alert_id_1, status="RESOLVED")
        self.assertTrue(resolved)

        alert_id_3 = create_curfew_alert(
            student_id=student_id,
            curfew_date=today,
            status="OVERDUE_OUT"
        )
        self.assertIsNotNone(alert_id_3)
        self.assertNotEqual(alert_id_1, alert_id_3)
        self.assertEqual(len(self.mock_client.curfew_alerts), 2)

    def test_system_settings_lifecycle(self):
        # Default curfew schedule exists
        curfew = get_system_settings("curfew_schedule")
        self.assertIsNotNone(curfew)
        self.assertEqual(curfew.get("start_time"), "17:00")
        self.assertEqual(curfew.get("end_time"), "19:30")

        # Non-existent key
        none_val = get_system_settings("non_existent_key")
        self.assertIsNone(none_val)

        # Update setting
        new_val = {"start_time": "18:00", "end_time": "20:00", "enabled": True}
        update_ok = update_system_settings("curfew_schedule", new_val)
        self.assertTrue(update_ok)

        curfew_updated = get_system_settings("curfew_schedule")
        self.assertEqual(curfew_updated.get("start_time"), "18:00")
        self.assertEqual(curfew_updated.get("end_time"), "20:00")

    def test_match_face_embedding_cosine_similarity(self):
        # Seed student 2 with different embedding
        student_2 = {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Ananya Sen",
            "roll_number": "2024-GH-0102",
            "room_number": "B-201",
            "embedding": [-0.1] * 512,
            "current_status": "IN"
        }
        self.mock_client.student_profiles.append(student_2)

        # Query embedding very close to student 1 (Priya: [0.1] * 512)
        query = [0.1] * 512
        matches = match_face_embedding(query, threshold=0.50, count=1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["name"], "Priya Sharma")
        self.assertGreaterEqual(matches[0]["similarity"], 0.99)

        # Test compatibility method
        compat_matches = match_hostel_face(query, threshold=0.50)
        self.assertEqual(len(compat_matches), 1)
        self.assertEqual(compat_matches[0]["name"], "Priya Sharma")

    def test_match_face_embedding_empty_input(self):
        empty_res = match_face_embedding([])
        self.assertEqual(empty_res, [])

    def test_mock_fallback_graceful_without_crash(self):
        client = get_hostel_client()
        self.assertIsNotNone(client)
        self.assertTrue(hasattr(client, "table"))

    def test_get_hostel_client_isolation_never_returns_unscoped_client(self):
        # 1. Client whose schema() raises an exception
        class FailingClient:
            def schema(self, schema_name):
                raise RuntimeError("Schema scoping refused")

        faulty = FailingClient()
        safe_1 = get_hostel_client(faulty)
        self.assertIsNot(safe_1, faulty)
        self.assertIsInstance(safe_1, MockHostelSupabaseClient)

        # 2. Client without schema() method
        class UnscopedClient:
            def table(self, name):
                return None

        unscoped = UnscopedClient()
        safe_2 = get_hostel_client(unscoped)
        self.assertIsNot(safe_2, unscoped)
        self.assertIsInstance(safe_2, MockHostelSupabaseClient)

        # 3. Client whose schema() returns None
        class NoneReturningClient:
            def schema(self, schema_name):
                return None

        none_client = NoneReturningClient()
        safe_3 = get_hostel_client(none_client)
        self.assertIsNot(safe_3, none_client)
        self.assertIsInstance(safe_3, MockHostelSupabaseClient)

        # 4. Injected faulty client
        set_hostel_client(faulty)
        safe_4 = get_hostel_client()
        self.assertIsNot(safe_4, faulty)
        self.assertIsInstance(safe_4, MockHostelSupabaseClient)

        reset_hostel_client()


if __name__ == "__main__":
    unittest.main()
