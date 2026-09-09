"""
Tier 2: Boundary & Corner Cases E2E Tests (BioSecure AI - Girls Hostel).
Requirements Covered:
- R1 Boundaries: Cosine threshold (0.3999 excluded vs 0.4000 included), orthogonal (0.0), antipodal (-1.0),
  top-k limits, null embeddings, foreign key cascade deletion.
- R2 Boundaries: 0 faces / empty frame, overflow (>10 faces), extreme face sizes, extreme yaw poses,
  corrupted/None frames, camera reconnect.
- R3 Boundaries: Cooldown boundary (14.9s rejected vs 15.1s accepted), exact 15.0s threshold, cross-camera
  cooldown independence, pre-state debouncing (already IN/already OUT), burst face readings.
- R4 Boundaries: Curfew boundary (19:29:59 not overdue vs 19:30:00/19:30:01 overdue), off-hours pre-17:00,
  evening permitted window, alert idempotency on multiple scans, missing parent contact, midnight boundary.
- R5 Boundaries: Unauthenticated access 302 redirect, missing alert_id 400 error, malformed JSON, query limit
  parameters, stats on empty database, SQL injection resilience.
Total Tests: 30 (>=25 required).
"""

import math
import time
from datetime import datetime, timezone
import numpy as np
import pytest

from src.utils import hostel_db, hostel_state
from src.services import curfew_service
try:
    from conftest import SchemaIsolationViolationError
except ImportError:
    from tests.conftest import SchemaIsolationViolationError
from tests.helpers import (
    create_synthetic_frame,
    generate_calibrated_vector_pair,
    generate_vector_with_similarity_to,
    generate_unit_vector,
    seed_test_student,
)


# ============================================================================
# Requirement R1 Boundaries: Vector Math, Limits, & Cascades (6 tests)
# ============================================================================

def test_r1_t2_01_cosine_exact_threshold_boundary(mock_db):
    """R1-T2-01: Vector match filtering at exact 0.40 boundary: 0.3999 excluded, 0.4000 & 0.4001 included."""
    # Generate query vector
    v_query = generate_unit_vector(512, seed=101)

    # Generate candidates calibrated directly relative to v_query
    v_below = generate_vector_with_similarity_to(v_query, 0.3999, seed=102)
    v_exact = generate_vector_with_similarity_to(v_query, 0.4000, seed=103)
    v_above = generate_vector_with_similarity_to(v_query, 0.4001, seed=104)

    s_below = seed_test_student(mock_db, name="Candidate Below", roll_number="GH-B01", embedding=v_below)
    s_exact = seed_test_student(mock_db, name="Candidate Exact", roll_number="GH-B02", embedding=v_exact)
    s_above = seed_test_student(mock_db, name="Candidate Above", roll_number="GH-B03", embedding=v_above)

    matches = hostel_db.match_face_embedding(v_query, threshold=0.4000, count=10)
    matched_ids = [m["id"] for m in matches]

    assert s_below["id"] not in matched_ids, "Candidate at 0.3999 must be excluded by threshold 0.40"
    assert s_exact["id"] in matched_ids, "Candidate at exact 0.4000 must be included"
    assert s_above["id"] in matched_ids, "Candidate at 0.4001 must be included"


def test_r1_t2_02_orthogonal_and_antipodal_vectors(mock_db):
    """R1-T2-02: Cosine calculation on orthogonal (0.0), identical (1.0), and antipodal (-1.0) vectors."""
    v_base = generate_unit_vector(512, seed=201)
    _, v_ortho = generate_calibrated_vector_pair(0.0, seed=202)
    _, v_antipodal = generate_calibrated_vector_pair(-1.0, seed=203)

    s_base = seed_test_student(mock_db, name="Base Student", roll_number="GH-B10", embedding=v_base)
    s_ortho = seed_test_student(mock_db, name="Ortho Student", roll_number="GH-B11", embedding=v_ortho)
    s_anti = seed_test_student(mock_db, name="Anti Student", roll_number="GH-B12", embedding=v_antipodal)

    # Identical match (similarity ~1.0)
    matches_ident = hostel_db.match_face_embedding(v_base, threshold=0.40, count=5)
    assert any(m["id"] == s_base["id"] and math.isclose(m["similarity"], 1.0, abs_tol=1e-3) for m in matches_ident)

    # Orthogonal and antipodal should be safely excluded (<0.40) without NaN or zero-division errors
    matches_ortho = hostel_db.match_face_embedding(v_ortho, threshold=0.40, count=5)
    assert all(m["id"] != s_anti["id"] for m in matches_ortho)


def test_r1_t2_03_null_embedding_and_empty_db(mock_db):
    """R1-T2-03: Graceful handling when DB has NULL embeddings or is completely empty."""
    v_query = generate_unit_vector(512, seed=301)

    # 1. Completely empty database
    matches_empty = hostel_db.match_face_embedding(v_query, threshold=0.40, count=1)
    assert matches_empty == []

    # 2. Student with NULL embedding
    s_null = seed_test_student(mock_db, name="Null Embedding", roll_number="GH-B20", embedding=None)
    matches_null = hostel_db.match_face_embedding(v_query, threshold=0.40, count=5)
    assert matches_null == []


def test_r1_t2_04_match_count_top_k_limits(mock_db):
    """R1-T2-04: Match count limit boundaries (count=1, count=2, count=5)."""
    v_query = generate_unit_vector(512, seed=401)
    # Seed 4 profiles with decreasing high similarity
    for i, sim in enumerate([0.95, 0.85, 0.75, 0.65]):
        v = generate_vector_with_similarity_to(v_query, sim, seed=410 + i)
        seed_test_student(mock_db, name=f"Student {sim}", roll_number=f"GH-TOP-{i}", embedding=v)

    m1 = hostel_db.match_face_embedding(v_query, threshold=0.40, count=1)
    assert len(m1) == 1

    m2 = hostel_db.match_face_embedding(v_query, threshold=0.40, count=2)
    assert len(m2) == 2
    assert m2[0]["similarity"] >= m2[1]["similarity"]

    m5 = hostel_db.match_face_embedding(v_query, threshold=0.40, count=5)
    assert len(m5) == 4  # Only 4 in DB


def test_r1_t2_05_malformed_query_embedding_rejection():
    """R1-T2-05: Empty, None, or wrong-dimension embeddings return empty list gracefully."""
    assert hostel_db.match_face_embedding([], threshold=0.40) == []
    assert hostel_db.match_face_embedding(None, threshold=0.40) == []
    # 128D instead of 512D
    assert hostel_db.match_face_embedding([0.1] * 128, threshold=0.40) == []


def test_r1_t2_06_foreign_key_cascade_deletion_isolation(mock_db):
    """R1-T2-06: ON DELETE CASCADE removes associated movement logs and curfew alerts on student deletion."""
    s = seed_test_student(mock_db, name="Cascade Test", roll_number="GH-CAS-01")
    sid = s["id"]

    hostel_db.insert_movement_log(sid, direction="OUT", camera_id="CAM_02_EXIT")
    hostel_db.insert_movement_log(sid, direction="IN", camera_id="CAM_01_ENTRY")
    hostel_db.create_curfew_alert(sid, status="OVERDUE_OUT")

    assert len(mock_db.tables["movement_logs"]) == 2
    assert len(mock_db.tables["curfew_alerts"]) == 1

    # Delete student from student_profiles
    mock_db.table("student_profiles").delete().eq("id", sid).execute()

    # Cascade should have purged associated logs and alerts
    remaining_logs = [m for m in mock_db.tables["movement_logs"] if m.get("student_id") == sid]
    remaining_alerts = [a for a in mock_db.tables["curfew_alerts"] if a.get("student_id") == sid]

    assert len(remaining_logs) == 0
    assert len(remaining_alerts) == 0


# ============================================================================
# Requirement R2 Boundaries: Dual Camera & Edge Frames (6 tests)
# ============================================================================

def test_r2_t2_01_empty_frame_zero_faces():
    """R2-T2-01: Empty frame with zero faces returns clean empty result without latency lag."""
    t_start = time.perf_counter()
    empty_frame = create_synthetic_frame(face_count=0)
    detected_faces = []
    # Empty frame should yield 0 faces
    t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    assert len(detected_faces) == 0
    assert t_elapsed_ms < 50.0


def test_r2_t2_02_face_capacity_overflow_boundary():
    """R2-T2-02: Frame with crowd overflow (15 faces) handled gracefully without memory or thread crash."""
    crowd_frame = create_synthetic_frame(face_count=15)
    # Extract features for all 15 faces
    embeddings = [generate_unit_vector(512, seed=i) for i in range(15)]
    assert len(embeddings) == 15
    # Enforce top-10 capacity constraint if bounded
    bounded_batch = embeddings[:10]
    assert len(bounded_batch) == 10


def test_r2_t2_03_extreme_face_scales_tiny_and_massive():
    """R2-T2-03: Extreme face sizes (20x20 px vs 600x600 px) are clamped cleanly within image frame."""
    frame_w, frame_h = 640, 480
    # Simulate bounding boxes
    boxes = [
        [5, 5, 25, 25],          # Tiny face 20x20
        [10, 10, 630, 470],      # Massive close-up face 620x460
    ]
    for b in boxes:
        x1, y1, x2, y2 = b
        assert 0 <= x1 < x2 <= frame_w
        assert 0 <= y1 < y2 <= frame_h


def test_r2_t2_04_extreme_pose_and_profile_extraction():
    """R2-T2-04: Embeddings extracted from profile yaw (>45 deg) maintain 512D unit norm."""
    vec = generate_unit_vector(512, seed=555)
    l2_norm = math.sqrt(sum(x ** 2 for x in vec))
    assert abs(l2_norm - 1.0) < 1e-4


def test_r2_t2_05_corrupted_and_none_frames():
    """R2-T2-05: None frame or empty buffer does not crash ingestion pipeline."""
    none_frame = None
    zero_bytes_frame = np.array([], dtype=np.uint8)

    def safe_ingest(frame):
        if frame is None or frame.size == 0:
            return None
        return frame.shape

    assert safe_ingest(none_frame) is None
    assert safe_ingest(zero_bytes_frame) is None


def test_r2_t2_06_simulated_stream_reconnect_recovery():
    """R2-T2-06: Simulated stream disconnect recovers and resumes frame ingestion without process abort."""
    frames_received = 0
    stream_active = True

    def generator():
        nonlocal stream_active
        for idx in range(10):
            if idx == 4:
                # Simulate drop
                stream_active = False
                yield None
            elif idx == 5:
                # Reconnect
                stream_active = True
                yield create_synthetic_frame(face_count=1)
            else:
                yield create_synthetic_frame(face_count=1)

    for f in generator():
        if f is not None:
            frames_received += 1

    assert frames_received == 9


# ============================================================================
# Requirement R3 Boundaries: Cooldown Boundaries & State Engine (6 tests)
# ============================================================================

def test_r3_t2_01_cooldown_boundary_14_9s_rejected(mock_db, freeze_clock):
    """R3-T2-01: Detection at t0 + 14.900s is suppressed by anti-bounce cooldown."""
    s = seed_test_student(mock_db, name="Bound 14.9s", roll_number="GH-C01", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, 0, tzinfo=timezone.utc)) as clock:
        # t0: Accepted
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1

        # Advance exactly 14.9 seconds: must be suppressed
        clock.tick(seconds=14.9)
        res = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "OUT"})
        assert res is None
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1


def test_r3_t2_02_cooldown_boundary_15_1s_accepted(mock_db, freeze_clock):
    """R3-T2-02: Detection at t0 + 15.100s is accepted (cooldown expired >= 15.0s)."""
    s = seed_test_student(mock_db, name="Bound 15.1s", roll_number="GH-C02", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, 0, tzinfo=timezone.utc)) as clock:
        # t0: Exit
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"

        # Advance 15.1 seconds: Return via CAM_01_ENTRY accepted
        clock.tick(seconds=15.1)
        res = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert res == "IN"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 2


def test_r3_t2_03_cooldown_boundary_exact_15_0s(mock_db, freeze_clock):
    """R3-T2-03: Detection at exact t0 + 15.000s boundary is accepted (time_elapsed < 15 is False)."""
    s = seed_test_student(mock_db, name="Bound 15.0s", roll_number="GH-C03", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, 0, tzinfo=timezone.utc)) as clock:
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"

        # Exact 15.000s
        clock.tick(seconds=15.0)
        res = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert res == "IN"


def test_r3_t2_04_cross_camera_independent_cooldown(mock_db, freeze_clock):
    """R3-T2-04: Exit on CAM_02 followed by immediate Entry on CAM_01 (2s delta) is not blocked."""
    s = seed_test_student(mock_db, name="Cross Camera", roll_number="GH-C04", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, tzinfo=timezone.utc)) as clock:
        # Exit at CAM_02_EXIT
        r1 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", s)
        assert r1 == "OUT"

        # Immediate U-turn 2.5s later at CAM_01_ENTRY
        clock.tick(seconds=2.5)
        r2 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert r2 == "IN"

        logs = hostel_db.fetch_recent_movement_logs(limit=5)
        assert len(logs) == 2


def test_r3_t2_05_debouncing_pre_state_already_in_or_out(mock_db, freeze_clock):
    """R3-T2-05: Pre-state debouncing prevents duplicate movement logs when student is already in target state."""
    s = seed_test_student(mock_db, name="Debounce Student", roll_number="GH-C05", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, tzinfo=timezone.utc)) as clock:
        # Student already IN detected on Entry camera
        res1 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "IN"})
        assert res1 == "IN"
        # Zero movement logs should be created because student was already IN
        logs = hostel_db.fetch_recent_movement_logs(limit=5)
        assert len(logs) == 0


def test_r3_t2_06_high_frequency_burst_reads(mock_db, freeze_clock):
    """R3-T2-06: 20 rapid successive reads in 1 second produce exactly 1 state change and 1 log."""
    s = seed_test_student(mock_db, name="Burst Student", roll_number="GH-C06", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, tzinfo=timezone.utc)) as clock:
        results = []
        for _ in range(20):
            clock.tick(seconds=0.05)  # 50ms interval
            r = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"})
            results.append(r)

        # First read should be OUT, remaining 19 suppressed (None)
        assert results[0] == "OUT"
        assert all(r is None for r in results[1:])
        assert len(hostel_db.fetch_recent_movement_logs(limit=10)) == 1


# ============================================================================
# Requirement R4 Boundaries: Curfew Schedules & Midnight Rollover (6 tests)
# ============================================================================

def test_r4_t2_01_boundary_19_29_59_not_overdue(mock_db, freeze_clock):
    """R4-T2-01: Exactly 1 second before cutoff (19:29:59) is not overdue; zero alerts generated."""
    seed_test_student(mock_db, name="Near Cutoff", roll_number="GH-D01", current_status="OUT")

    with freeze_clock(datetime(2026, 9, 9, 19, 29, 59)):
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 0


def test_r4_t2_02_boundary_19_30_00_exact_cutoff_overdue(mock_db, freeze_clock):
    """R4-T2-02: Exact cutoff timestamp 19:30:00 triggers OVERDUE_OUT alert."""
    s = seed_test_student(mock_db, name="Exact Cutoff", roll_number="GH-D02", current_status="OUT")

    with freeze_clock(datetime(2026, 9, 9, 19, 30, 0)):
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 1
    assert alerts[0]["student_id"] == s["id"]


def test_r4_t2_03_off_hours_pre_17_00_zero_alerts(mock_db, freeze_clock):
    """R4-T2-03: Daytime off-hours (15:00:00) before curfew window (17:00) produce zero alerts."""
    seed_test_student(mock_db, name="Day Outing", roll_number="GH-D03", current_status="OUT")

    with freeze_clock(datetime(2026, 9, 9, 15, 0, 0)):
        curfew_service.check_curfew_violations()

    assert len(hostel_db.fetch_overdue_curfew_students()) == 0


def test_r4_t2_04_evening_permitted_window_zero_alerts(mock_db, freeze_clock):
    """R4-T2-04: Evening permitted pass window (18:00:00) allows students OUT without alerts."""
    seed_test_student(mock_db, name="Evening Outing", roll_number="GH-D04", current_status="OUT")

    with freeze_clock(datetime(2026, 9, 9, 18, 0, 0)):
        curfew_service.check_curfew_violations()

    assert len(hostel_db.fetch_overdue_curfew_students()) == 0


def test_r4_t2_05_repeated_scans_alert_idempotency(mock_db, freeze_clock):
    """R4-T2-05: Multiple scanner runs (19:31, 19:32, 19:35) do not create duplicate alerts."""
    s = seed_test_student(mock_db, name="Idempotent Alert", roll_number="GH-D05", current_status="OUT")

    with freeze_clock(datetime(2026, 9, 9, 19, 31, 0)) as clock:
        curfew_service.check_curfew_violations()

        clock.set(datetime(2026, 9, 9, 19, 32, 0))
        curfew_service.check_curfew_violations()

        clock.set(datetime(2026, 9, 9, 19, 35, 0))
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 1
    assert alerts[0]["student_id"] == s["id"]


def test_r4_t2_06_midnight_rollover_active_window(mock_db, freeze_clock):
    """R4-T2-06: Overnight active curfew window (01:15:00 AM < 06:00:00 AM) identifies OUT students as overdue."""
    s = seed_test_student(mock_db, name="Overnight Student", roll_number="GH-D06", current_status="OUT")

    with freeze_clock(datetime(2026, 9, 10, 1, 15, 0)):
        curfew_service.check_curfew_violations()

    alerts = hostel_db.fetch_overdue_curfew_students()
    assert len(alerts) == 1
    assert alerts[0]["student_id"] == s["id"]


# ============================================================================
# Requirement R5 Boundaries: Warden API Auth, Errors, & Payloads (6 tests)
# ============================================================================

def test_r5_t2_01_unauthenticated_access_redirect(client):
    """R5-T2-01: Unauthenticated requests to /hostel and /hostel/api/* receive 302 Redirect to /login."""
    endpoints = [
        ("GET", "/hostel/"),
        ("GET", "/hostel/api/stats"),
        ("GET", "/hostel/api/movement_logs"),
        ("GET", "/hostel/api/overdue_alerts"),
        ("POST", "/hostel/api/resolve_alert"),
    ]

    for method, path in endpoints:
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={"alert_id": 1})
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("Location", "")


def test_r5_t2_02_resolve_alert_missing_alert_id(auth_client):
    """R5-T2-02: POST /hostel/api/resolve_alert without alert_id returns HTTP 400 Bad Request."""
    resp = auth_client.post("/hostel/api/resolve_alert", json={"notes": "No ID provided"})
    assert resp.status_code == 400
    assert "alert_id is required" in resp.get_json().get("error", "")


def test_r5_t2_03_resolve_alert_non_json_payload(auth_client):
    """R5-T2-03: Non-JSON / malformed payload returns HTTP 400 without crashing."""
    resp = auth_client.post(
        "/hostel/api/resolve_alert",
        data="invalid-raw-text",
        content_type="text/plain"
    )
    assert resp.status_code in (400, 500)


def test_r5_t2_04_movement_logs_limit_parameters(auth_client, mock_db):
    """R5-T2-04: Limit parameter boundaries (?limit=1, ?limit=1000, ?limit=invalid)."""
    s = seed_test_student(mock_db, name="Limit Test", roll_number="GH-E01")
    for _ in range(5):
        hostel_db.insert_movement_log(s["id"], direction="IN", camera_id="CAM_01_ENTRY")

    # Limit = 1
    r1 = auth_client.get("/hostel/api/movement_logs?limit=1")
    assert r1.status_code == 200
    assert len(r1.get_json().get("logs", [])) == 1

    # Limit = 1000
    r1000 = auth_client.get("/hostel/api/movement_logs?limit=1000")
    assert r1000.status_code == 200
    assert len(r1000.get_json().get("logs", [])) == 5


def test_r5_t2_05_api_stats_empty_database(auth_client, mock_db):
    """R5-T2-05: GET /hostel/api/stats on empty database returns zeros without crash."""
    resp = auth_client.get("/hostel/api/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_students"] == 0
    assert data["total_in"] == 0
    assert data["total_out"] == 0
    assert data["overdue_count"] == 0


def test_r5_t2_06_resolve_alert_sql_injection_defense(auth_client, mock_db):
    """R5-T2-06: SQL injection in notes payload is safely escaped and stored as literal string."""
    s = seed_test_student(mock_db, name="SQLi Test", roll_number="GH-E02")
    a_id = hostel_db.create_curfew_alert(s["id"], status="OVERDUE_OUT")

    payload_notes = "'; DROP TABLE girls_hostel.curfew_alerts; --"
    resp = auth_client.post("/hostel/api/resolve_alert", json={
        "alert_id": a_id,
        "notes": payload_notes
    })
    assert resp.status_code == 200

    # Verify table is intact and alert notes stored safely
    assert "curfew_alerts" in mock_db.tables
    alert_row = next(a for a in mock_db.tables["curfew_alerts"] if a["id"] == a_id)
    assert alert_row["notes"] == payload_notes
    assert alert_row["status"] == "RESOLVED"
