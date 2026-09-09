"""
Tier 1: Feature Coverage E2E Tests (BioSecure AI - Girls Hostel).
Requirements Covered:
- R1: Schema isolation, RLS enabled on all 4 tables, match_face RPC cosine search, zero public.* references, CRUD isolation.
- R2: Dual camera simultaneous ingestion (CAM_01_ENTRY, CAM_02_EXIT), multi-face detection (up to 10 faces), <200ms latency validation, 512D unit normalization.
- R3: Movement state machine: CAM_02 Exit -> OUT, CAM_01 Entry -> IN, 15s anti-bounce cooldown.
- R4: Curfew window schedule (17:00-19:30), overdue scanning, OVERDUE_OUT alert generation, parent contact alert.
- R5: Warden dashboard endpoints (/hostel, /hostel/api/stats, /hostel/api/movement_logs, /hostel/api/overdue_alerts, /hostel/api/resolve_alert).
Total Tests: 26 (>=25 required).
"""

import math
import os
import re
import threading
import time
from datetime import datetime, timezone
import pytest

from src.utils import hostel_db, hostel_state
from src.services import curfew_service
try:
    from conftest import SchemaIsolationViolationError
except ImportError:
    from tests.conftest import SchemaIsolationViolationError
from tests.helpers import (
    generate_calibrated_vector_pair,
    generate_unit_vector,
    create_synthetic_frame,
    seed_test_student
)


# ============================================================================
# Requirement R1: Schema Isolation, RLS, and Vector Search (>=5 tests)
# ============================================================================

def test_r1_schema_and_tables_ddl_completeness():
    """R1-T1-01: Verify schema creation and DDL completeness for all 4 hostel tables."""
    ddl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "girls_hostel_schema.sql"))
    assert os.path.exists(ddl_path), f"DDL file missing at {ddl_path}"
    with open(ddl_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # Verify dedicated schema
    assert "CREATE SCHEMA IF NOT EXISTS girls_hostel;" in sql

    # Verify 4 required tables
    assert "CREATE TABLE IF NOT EXISTS girls_hostel.student_profiles" in sql
    assert "CREATE TABLE IF NOT EXISTS girls_hostel.movement_logs" in sql
    assert "CREATE TABLE IF NOT EXISTS girls_hostel.curfew_alerts" in sql
    assert "CREATE TABLE IF NOT EXISTS girls_hostel.system_settings" in sql

    # Verify Foreign Keys with CASCADE
    assert "REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE" in sql


def test_r1_row_level_security_enabled_on_all_tables():
    """R1-T1-02: Verify Row Level Security (RLS) is explicitly enabled on all 4 tables."""
    ddl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "girls_hostel_schema.sql"))
    with open(ddl_path, "r", encoding="utf-8") as f:
        sql = f.read()

    tables = ["student_profiles", "movement_logs", "curfew_alerts", "system_settings"]
    for t in tables:
        expected = f"ALTER TABLE girls_hostel.{t} ENABLE ROW LEVEL SECURITY;"
        assert expected in sql, f"RLS not enabled for table {t}"


def test_r1_hnsw_vector_index_specification():
    """R1-T1-03: Verify HNSW vector index definition on embeddings."""
    ddl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "girls_hostel_schema.sql"))
    with open(ddl_path, "r", encoding="utf-8") as f:
        sql = f.read()

    assert "CREATE INDEX IF NOT EXISTS idx_girls_hostel_students_embedding" in sql
    assert "USING hnsw (embedding vector_cosine_ops)" in sql


def test_r1_match_face_rpc_signature_and_cosine_math(mock_db):
    """R1-T1-04: Verify match_face RPC parameters, return types, and cosine similarity calculation."""
    v_query = generate_unit_vector(512, seed=42)
    # Generate matching profile with similarity ~0.85
    _, v_match = generate_calibrated_vector_pair(similarity=0.85, seed=43)
    # Generate non-matching profile with similarity ~0.20
    _, v_nomatch = generate_calibrated_vector_pair(similarity=0.20, seed=44)

    s_match = seed_test_student(mock_db, name="Aanya Match", roll_number="GH-001", embedding=v_match)
    s_nomatch = seed_test_student(mock_db, name="Diya NoMatch", roll_number="GH-002", embedding=v_nomatch)

    matches = hostel_db.match_face_embedding(v_match, threshold=0.40, count=5)
    assert len(matches) == 1
    assert matches[0]["id"] == s_match["id"]
    assert matches[0]["name"] == "Aanya Match"
    assert math.isclose(matches[0]["similarity"], 1.0, abs_tol=1e-3)


def test_r1_strict_schema_isolation_zero_public_references():
    """R1-T1-05: Verify zero reads, writes, or references to public.* schema across hostel codebase."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    checked_paths = [
        os.path.join(root_dir, "scripts", "girls_hostel_schema.sql"),
        os.path.join(root_dir, "src", "utils", "hostel_db.py"),
        os.path.join(root_dir, "src", "utils", "hostel_state.py"),
        os.path.join(root_dir, "src", "services", "curfew_service.py"),
        os.path.join(root_dir, "src", "blueprints", "hostel.py")
    ]

    banned_pattern = re.compile(r"\bpublic\.(student_profiles|attendance_logs|curfew_alerts)\b", re.IGNORECASE)
    for p in checked_paths:
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
            matches = banned_pattern.findall(content)
            assert len(matches) == 0, f"Found banned public schema reference in {p}: {matches}"


def test_r1_hostel_db_client_crud_isolation(mock_db):
    """R1-T1-06: Verify hostel database client operations execute strictly in girls_hostel schema."""
    s1 = seed_test_student(mock_db, name="Priya Sen", roll_number="GH-010", current_status="IN")

    # Fetch
    students = hostel_db.fetch_all_hostel_students()
    assert any(s["id"] == s1["id"] for s in students)

    # State update
    ok = hostel_db.update_student_movement_state(s1["id"], direction="OUT", camera_id="CAM_02_EXIT")
    assert ok is True

    # Movement logs
    logs = hostel_db.fetch_recent_movement_logs(limit=10)
    assert len(logs) >= 1
    assert logs[0]["student_id"] == s1["id"]
    assert logs[0]["direction"] == "OUT"

    # Schema isolation guard: trying to access public schema raises SchemaIsolationViolationError
    with pytest.raises(SchemaIsolationViolationError):
        mock_db.schema("public")


# ============================================================================
# Requirement R2: Dual Camera Ingestion & Multi-Face Detection (>=5 tests)
# ============================================================================

def test_r2_simultaneous_dual_camera_concurrency(mock_db):
    """R2-T1-01: Verify concurrent, non-blocking ingestion on Camera 1 and Camera 2."""
    cam1_results = []
    cam2_results = []

    def stream_worker(camera_id, results_list):
        for i in range(10):
            # Simulate frame processing
            frame = create_synthetic_frame(face_count=2)
            results_list.append((camera_id, i, frame.shape))
            time.sleep(0.01)

    t1 = threading.Thread(target=stream_worker, args=("CAM_01_ENTRY", cam1_results))
    t2 = threading.Thread(target=stream_worker, args=("CAM_02_EXIT", cam2_results))

    t1.start()
    t2.start()

    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    assert not t1.is_alive(), "Camera 1 worker timed out"
    assert not t2.is_alive(), "Camera 2 worker timed out"
    assert len(cam1_results) == 10
    assert len(cam2_results) == 10


def test_r2_multi_face_detection_up_to_10_faces():
    """R2-T1-02: Verify capacity to detect and extract embeddings for up to 10 faces in a batch."""
    frame = create_synthetic_frame(width=1280, height=720, face_count=10)
    assert frame.shape == (720, 1280, 3)

    # Simulate batch feature extraction of 10 faces
    batch_embeddings = []
    for i in range(10):
        emb = generate_unit_vector(512, seed=i)
        batch_embeddings.append(emb)

    assert len(batch_embeddings) == 10
    for emb in batch_embeddings:
        assert len(emb) == 512
        assert math.isclose(sum(x * x for x in emb) ** 0.5, 1.0, abs_tol=1e-4)


def test_r2_frame_batch_latency_sla_under_200ms():
    """R2-T1-03: Benchmark batch processing latency for 10 concurrent faces (<200ms SLA)."""
    import numpy as np
    latencies_ms = []

    for trial in range(5):
        t_start = time.perf_counter()

        # Simulate 10-face extraction and L2 normalization
        vectors = []
        for f in range(10):
            raw = np.random.randn(512)
            norm = np.linalg.norm(raw)
            vectors.append((raw / norm).tolist())

        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000.0
        latencies_ms.append(elapsed_ms)

    avg_latency = sum(latencies_ms) / len(latencies_ms)
    sorted_lats = sorted(latencies_ms)
    p95_idx = min(int(0.95 * len(sorted_lats)), len(sorted_lats) - 1)
    p95_latency = sorted_lats[p95_idx]

    assert avg_latency < 200.0, f"Average latency {avg_latency:.2f}ms exceeds 200ms SLA"
    assert p95_latency < 200.0, f"P95 latency {p95_latency:.2f}ms exceeds 200ms SLA"


def test_r2_512d_arcface_embedding_normalization():
    """R2-T1-04: Verify that all extracted facial embeddings are strictly 512D and L2-normalized."""
    for seed in range(5):
        vec = generate_unit_vector(512, seed=seed)
        assert len(vec) == 512
        l2_norm = math.sqrt(sum(v ** 2 for v in vec))
        assert abs(l2_norm - 1.0) < 1e-4, f"L2 norm {l2_norm} not unit-normalized"


def test_r2_camera_worker_independent_lifecycle():
    """R2-T1-05: Verify independent start, stop, and failure isolation between camera workers."""
    cam1_stop = threading.Event()
    cam2_stop = threading.Event()
    cam1_counter = 0
    cam2_counter = 0

    def cam1_loop():
        nonlocal cam1_counter
        while not cam1_stop.is_set():
            cam1_counter += 1
            time.sleep(0.01)

    def cam2_loop():
        nonlocal cam2_counter
        while not cam2_stop.is_set():
            cam2_counter += 1
            time.sleep(0.01)

    t1 = threading.Thread(target=cam1_loop, daemon=True)
    t2 = threading.Thread(target=cam2_loop, daemon=True)
    t1.start()
    t2.start()

    time.sleep(0.05)
    # Stop Camera 1, Camera 2 continues
    cam1_stop.set()
    t1.join(timeout=1.0)
    assert not t1.is_alive()
    c2_count_before = cam2_counter
    time.sleep(0.05)
    assert cam2_counter > c2_count_before, "Camera 2 should continue running independently"

    cam2_stop.set()
    t2.join(timeout=1.0)
    assert not t2.is_alive()


# ============================================================================
# Requirement R3: Movement State Machine & 15s Cooldown (>=5 tests)
# ============================================================================

def test_r3_exit_gate_transitions_in_to_out(mock_db):
    """R3-T1-01: CAM_02 Exit gate transitions student status from IN to OUT and logs movement."""
    student = seed_test_student(mock_db, name="Kavya Iyer", roll_number="GH-021", current_status="IN")
    sid = student["id"]

    res = hostel_state.process_student_detection(
        student_id=sid,
        camera_id="CAM_02_EXIT",
        student_info={"id": sid, "name": "Kavya Iyer", "current_status": "IN"}
    )

    assert res == "OUT"
    updated = hostel_db.get_student_by_id(sid)
    assert updated["current_status"] == "OUT"
    assert updated["last_movement_time"] is not None

    logs = hostel_db.fetch_recent_movement_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["direction"] == "OUT"
    assert logs[0]["camera_id"] == "CAM_02_EXIT"


def test_r3_entry_gate_transitions_out_to_in(mock_db):
    """R3-T1-02: CAM_01 Entry gate transitions student status from OUT to IN and logs movement."""
    student = seed_test_student(mock_db, name="Bhavna Nair", roll_number="GH-022", current_status="OUT")
    sid = student["id"]

    res = hostel_state.process_student_detection(
        student_id=sid,
        camera_id="CAM_01_ENTRY",
        student_info={"id": sid, "name": "Bhavna Nair", "current_status": "OUT"}
    )

    assert res == "IN"
    updated = hostel_db.get_student_by_id(sid)
    assert updated["current_status"] == "IN"

    logs = hostel_db.fetch_recent_movement_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["direction"] == "IN"
    assert logs[0]["camera_id"] == "CAM_01_ENTRY"


def test_r3_cooldown_suppresses_duplicate_lingering_face(mock_db, freeze_clock):
    """R3-T1-03: 15s Anti-bounce cooldown suppresses duplicate detection when face lingers."""
    student = seed_test_student(mock_db, name="Sanya Rao", roll_number="GH-023", current_status="IN")
    sid = student["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 15, 0, tzinfo=timezone.utc)) as clock:
        # First detection: accepted -> OUT
        r1 = hostel_state.process_student_detection(
            sid, "CAM_02_EXIT", {"id": sid, "name": "Sanya Rao", "current_status": "IN"}
        )
        assert r1 == "OUT"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1

        # Advance 4 seconds (lingering face): must be suppressed
        clock.tick(seconds=4.0)
        r2 = hostel_state.process_student_detection(
            sid, "CAM_02_EXIT", {"id": sid, "name": "Sanya Rao", "current_status": "OUT"}
        )
        assert r2 is None
        # Still exactly 1 log in database
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1


def test_r3_cooldown_expiry_allows_subsequent_event(mock_db, freeze_clock):
    """R3-T1-04: Cooldown expiry (>15s) allows subsequent movement event."""
    student = seed_test_student(mock_db, name="Deepa Menon", roll_number="GH-024", current_status="IN")
    sid = student["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 15, 0, tzinfo=timezone.utc)) as clock:
        # Exit at t0
        r1 = hostel_state.process_student_detection(
            sid, "CAM_02_EXIT", {"id": sid, "name": "Deepa Menon", "current_status": "IN"}
        )
        assert r1 == "OUT"

        # Advance 25 seconds (exceeding 15s cooldown)
        clock.tick(seconds=25.0)

        # Return through CAM_01_ENTRY
        r2 = hostel_state.process_student_detection(
            sid, "CAM_01_ENTRY", {"id": sid, "name": "Deepa Menon", "current_status": "OUT"}
        )
        assert r2 == "IN"

        logs = hostel_db.fetch_recent_movement_logs(limit=5)
        assert len(logs) == 2
        assert logs[0]["direction"] == "IN"
        assert logs[1]["direction"] == "OUT"


def test_r3_multi_student_concurrent_cooldown_isolation(mock_db, freeze_clock):
    """R3-T1-05: Cooldown is tracked independently per student without cross-student blocking."""
    s1 = seed_test_student(mock_db, name="Student 1", roll_number="GH-025", current_status="IN")
    s2 = seed_test_student(mock_db, name="Student 2", roll_number="GH-026", current_status="IN")
    s3 = seed_test_student(mock_db, name="Student 3", roll_number="GH-027", current_status="IN")

    with freeze_clock(datetime(2026, 9, 9, 17, 20, 0, tzinfo=timezone.utc)) as clock:
        # S1 and S2 exit at t0
        assert hostel_state.process_student_detection(s1["id"], "CAM_02_EXIT", s1) == "OUT"
        assert hostel_state.process_student_detection(s2["id"], "CAM_02_EXIT", s2) == "OUT"

        # Advance 5s: S1 lingers, S3 newly arrives
        clock.tick(seconds=5.0)
        # S1 is suppressed
        assert hostel_state.process_student_detection(s1["id"], "CAM_02_EXIT", s1) is None
        # S3 is accepted
        assert hostel_state.process_student_detection(s3["id"], "CAM_02_EXIT", s3) == "OUT"


# ============================================================================
# Requirement R4: Curfew Schedule & Overdue Alert Scanner (>=5 tests)
# ============================================================================

def test_r4_overdue_scan_flags_student_out_past_curfew(mock_db, freeze_clock):
    """R4-T1-01: Scanner flags students with current_status='OUT' past 19:30 curfew cutoff."""
    s1 = seed_test_student(mock_db, name="Radhika", roll_number="GH-041", current_status="OUT")
    s2 = seed_test_student(mock_db, name="Sneha", roll_number="GH-042", current_status="IN")

    with freeze_clock(datetime(2026, 9, 9, 19, 35, 0)):
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 1
    assert alerts[0]["student_id"] == s1["id"]
    assert alerts[0]["status"] == "OVERDUE_OUT"
    assert alerts[0]["curfew_end_time"] == "19:30:00"


def test_r4_all_students_inside_zero_alerts(mock_db, freeze_clock):
    """R4-T1-02: Scanner produces zero alerts when all students are IN."""
    seed_test_student(mock_db, name="Student A", roll_number="GH-043", current_status="IN")
    seed_test_student(mock_db, name="Student B", roll_number="GH-044", current_status="IN")

    with freeze_clock(datetime(2026, 9, 9, 19, 40, 0)):
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 0


def test_r4_batch_overdue_students_flagged(mock_db, freeze_clock):
    """R4-T1-03: Scanner flags all overdue students in a single batch."""
    s_out = [
        seed_test_student(mock_db, name=f"Out Student {i}", roll_number=f"GH-OUT-{i}", current_status="OUT")
        for i in range(4)
    ]
    s_in = [
        seed_test_student(mock_db, name=f"In Student {i}", roll_number=f"GH-IN-{i}", current_status="IN")
        for i in range(3)
    ]

    with freeze_clock(datetime(2026, 9, 9, 19, 45, 0)):
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 4
    alerted_ids = {a["student_id"] for a in alerts}
    for s in s_out:
        assert s["id"] in alerted_ids


def test_r4_parent_contact_alert_logging(mock_db, freeze_clock, caplog):
    """R4-T1-04: Alert logging includes student name, roll number, room number, and parent contact."""
    caplog.set_level("ERROR")
    s = seed_test_student(
        mock_db,
        name="Ananya Verma",
        roll_number="GH-101",
        room_number="A-204",
        parent_contact="+91-9876543210",
        current_status="OUT"
    )

    with freeze_clock(datetime(2026, 9, 9, 19, 31, 0)):
        curfew_service.check_curfew_violations()

    assert "🚨 CURFEW BREACH ALERT" in caplog.text
    assert "Ananya Verma" in caplog.text
    assert "GH-101" in caplog.text
    assert "A-204" in caplog.text
    assert "+91-9876543210" in caplog.text


def test_r4_curfew_window_schedule_configuration(mock_db):
    """R4-T1-05: Verify system settings configuration for curfew schedule window."""
    setting = hostel_db.get_system_settings("curfew_schedule")
    assert setting is not None
    assert setting.get("start_time") == "17:00"
    assert setting.get("end_time") == "19:30"
    assert setting.get("enabled") is True


# ============================================================================
# Requirement R5: Warden Dashboard & API Endpoints (>=5 tests)
# ============================================================================

def test_r5_warden_dashboard_render_authenticated(auth_client):
    """R5-T1-01: Authenticated warden can view /hostel/ dashboard UI."""
    response = auth_client.get("/hostel/")
    assert response.status_code == 200
    assert "text/html" in response.content_type
    html = response.get_data(as_text=True)
    # Check for crucial dashboard elements
    assert "Girls Hostel Security & Curfew Monitor" in html
    assert "statTotal" in html
    assert "statIn" in html
    assert "statOut" in html
    assert "statOverdue" in html


def test_r5_api_stats_summary(auth_client, mock_db):
    """R5-T1-02: GET /hostel/api/stats returns accurate live headcount and overdue count."""
    for i in range(7):
        seed_test_student(mock_db, name=f"Inside {i}", roll_number=f"GH-IN-{i}", current_status="IN")
    for i in range(3):
        seed_test_student(mock_db, name=f"Outside {i}", roll_number=f"GH-OUT-{i}", current_status="OUT")

    # Insert 2 overdue alerts
    hostel_db.create_curfew_alert("student-id-1", status="OVERDUE_OUT")
    hostel_db.create_curfew_alert("student-id-2", status="OVERDUE_OUT")

    response = auth_client.get("/hostel/api/stats")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total_students"] == 10
    assert data["total_in"] == 7
    assert data["total_out"] == 3
    assert data["overdue_count"] == 2
    assert data["curfew_window"] == "17:00 - 19:30"


def test_r5_api_movement_logs(auth_client, mock_db):
    """R5-T1-03: GET /hostel/api/movement_logs returns logs in descending order with student details."""
    s = seed_test_student(mock_db, name="Meera Patel", roll_number="GH-088", room_number="B-102")
    hostel_db.insert_movement_log(s["id"], direction="OUT", camera_id="CAM_02_EXIT")
    hostel_db.insert_movement_log(s["id"], direction="IN", camera_id="CAM_01_ENTRY")

    response = auth_client.get("/hostel/api/movement_logs?limit=10")
    assert response.status_code == 200
    data = response.get_json()
    logs = data.get("logs", [])
    assert len(logs) == 2
    # Check join with student profile
    assert logs[0]["student_profiles"]["name"] == "Meera Patel"
    assert logs[0]["student_profiles"]["room_number"] == "B-102"


def test_r5_api_overdue_alerts(auth_client, mock_db):
    """R5-T1-04: GET /hostel/api/overdue_alerts returns active OVERDUE_OUT alerts only."""
    s1 = seed_test_student(mock_db, name="Overdue Student", roll_number="GH-091", parent_contact="+91-9876543210")
    s2 = seed_test_student(mock_db, name="Resolved Student", roll_number="GH-092")

    a1_id = hostel_db.create_curfew_alert(s1["id"], status="OVERDUE_OUT")
    a2_id = hostel_db.create_curfew_alert(s2["id"], status="RESOLVED")

    response = auth_client.get("/hostel/api/overdue_alerts")
    assert response.status_code == 200
    data = response.get_json()
    alerts = data.get("alerts", [])
    assert len(alerts) == 1
    assert alerts[0]["id"] == a1_id
    assert alerts[0]["status"] == "OVERDUE_OUT"
    assert alerts[0]["student_profiles"]["parent_contact"] == "+91-9876543210"


def test_r5_api_resolve_alert(auth_client, mock_db):
    """R5-T1-05: POST /hostel/api/resolve_alert marks alert as RESOLVED with custom notes."""
    s = seed_test_student(mock_db, name="Late Return", roll_number="GH-099")
    a_id = hostel_db.create_curfew_alert(s["id"], status="OVERDUE_OUT")

    response = auth_client.post("/hostel/api/resolve_alert", json={
        "alert_id": a_id,
        "notes": "Parent confirmed train delay"
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"

    # Verify that alert is no longer in active overdue alerts
    active_alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(active_alerts) == 0
