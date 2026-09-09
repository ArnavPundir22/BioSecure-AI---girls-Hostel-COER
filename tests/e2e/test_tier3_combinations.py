"""
Tier 3: Cross-Feature Combinations E2E Tests (BioSecure AI - Girls Hostel).
Tests complex multi-component interactions across:
- R1 (Schema Isolation & Vector RPC)
- R2 (Dual Camera & Multi-Face Ingestion)
- R3 (Movement State Machine & Anti-Bounce Cooldown)
- R4 (Curfew Schedule & Overdue Alert Scanner)
- R5 (Warden Dashboard & Control Center APIs)
Total Tests: 10 (>=8 required).
"""

import math
import threading
import time
from datetime import datetime, timezone
try:
    from conftest import MockSupabaseHostelClient
except ImportError:
    from tests.conftest import MockSupabaseHostelClient

from src.utils import hostel_db, hostel_state
from src.services import curfew_service
from tests.helpers import (
    generate_calibrated_vector_pair,
    generate_unit_vector,
    seed_test_student,
)


def test_t3_01_departure_return_lifecycle_with_dashboard_sync(auth_client, mock_db, freeze_clock):
    """T3-01: Full lifecycle departure & return syncs state, movement logs, and live dashboard stats."""
    s1 = seed_test_student(mock_db, name="Anika Sen", roll_number="GH-301", current_status="IN")
    sid = s1["id"]

    # Initial state verification
    r_stats0 = auth_client.get("/hostel/api/stats").get_json()
    assert r_stats0["total_in"] == 1
    assert r_stats0["total_out"] == 0

    with freeze_clock(datetime(2026, 9, 9, 17, 10, 0, tzinfo=timezone.utc)) as clock:
        # Step 1: Exit via CAM_02_EXIT
        dir1 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", s1)
        assert dir1 == "OUT"

        # Verify stats updated
        r_stats1 = auth_client.get("/hostel/api/stats").get_json()
        assert r_stats1["total_in"] == 0
        assert r_stats1["total_out"] == 1

        # Verify movement logs
        logs1 = auth_client.get("/hostel/api/movement_logs?limit=5").get_json()["logs"]
        assert len(logs1) == 1
        assert logs1[0]["direction"] == "OUT"

        # Step 2: Advance time by 20s (exceeding 15s cooldown) and return via CAM_01_ENTRY
        clock.tick(seconds=20.0)
        dir2 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert dir2 == "IN"

        # Verify stats reverted
        r_stats2 = auth_client.get("/hostel/api/stats").get_json()
        assert r_stats2["total_in"] == 1
        assert r_stats2["total_out"] == 0

        # Verify movement logs descending order
        logs2 = auth_client.get("/hostel/api/movement_logs?limit=5").get_json()["logs"]
        assert len(logs2) == 2
        assert logs2[0]["direction"] == "IN"
        assert logs2[1]["direction"] == "OUT"


def test_t3_02_entry_cooldown_curfew_immunity(auth_client, mock_db, freeze_clock):
    """T3-02: Student returns at 19:28, lingers in gate view (debounced), 19:30 curfew scan flags 0 alerts."""
    s = seed_test_student(mock_db, name="Tanvi Das", roll_number="GH-302", current_status="OUT")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 19, 28, 0, tzinfo=timezone.utc)) as clock:
        # Arrives on CAM_01_ENTRY
        res1 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", s)
        assert res1 == "IN"

        # Lingers 5s and 10s later in front of camera
        clock.tick(seconds=5.0)
        assert hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "IN"}) is None
        clock.tick(seconds=5.0)
        assert hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "IN"}) is None

        # Advance to 19:30:05 (past curfew deadline)
        clock.set(datetime(2026, 9, 9, 19, 30, 5))
        curfew_service.check_curfew_violations()

        # Student is IN, so zero alerts
        r_alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(r_alerts) == 0

        r_stats = auth_client.get("/hostel/api/stats").get_json()
        assert r_stats["overdue_count"] == 0
        assert r_stats["total_in"] == 1


def test_t3_03_exit_curfew_breach_alert_resolution_reentry(auth_client, mock_db, freeze_clock):
    """T3-03: Exit -> Curfew Breach -> Alert Generation -> Warden Resolution -> Gate Re-entry."""
    s = seed_test_student(
        mock_db,
        name="Pooja Sharma",
        roll_number="GH-303",
        room_number="C-301",
        parent_contact="+91-9876543210",
        current_status="IN"
    )
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 30, 0, tzinfo=timezone.utc)) as clock:
        # Phase 1: Exit
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"

        # Phase 2: Curfew Cutoff at 19:30:01
        clock.set(datetime(2026, 9, 9, 19, 30, 1))
        curfew_service.check_curfew_violations()

        # Phase 3: Warden views alert on dashboard
        alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts) == 1
        alert_id = alerts[0]["id"]
        assert alerts[0]["student_profiles"]["name"] == "Pooja Sharma"
        assert alerts[0]["student_profiles"]["parent_contact"] == "+91-9876543210"

        # Phase 4: Warden resolves alert with notes
        res_post = auth_client.post("/hostel/api/resolve_alert", json={
            "alert_id": alert_id,
            "notes": "Parent confirmed arrival at 19:45"
        })
        assert res_post.status_code == 200

        # Active overdue alerts now empty
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0

        # Phase 5: Student returns at 19:45
        clock.set(datetime(2026, 9, 9, 19, 45, 0, tzinfo=timezone.utc))
        assert hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"}) == "IN"

        # Scanner runs again at 19:46: zero alerts
        clock.set(datetime(2026, 9, 9, 19, 46, 0))
        curfew_service.check_curfew_violations()
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0


def test_t3_04_concurrent_dual_gate_simultaneous_detections(auth_client, mock_db):
    """T3-04: Concurrent threads triggering Entry and Exit simultaneously maintain database consistency."""
    s_a = seed_test_student(mock_db, name="Student Alpha", roll_number="GH-A01", current_status="IN")
    s_b = seed_test_student(mock_db, name="Student Beta", roll_number="GH-B01", current_status="OUT")

    results = {}

    def run_exit():
        results["exit"] = hostel_state.process_student_detection(s_a["id"], "CAM_02_EXIT", s_a)

    def run_entry():
        results["entry"] = hostel_state.process_student_detection(s_b["id"], "CAM_01_ENTRY", s_b)

    t1 = threading.Thread(target=run_exit)
    t2 = threading.Thread(target=run_entry)

    t1.start()
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert results.get("exit") == "OUT"
    assert results.get("entry") == "IN"

    stats = auth_client.get("/hostel/api/stats").get_json()
    assert stats["total_students"] == 2
    assert stats["total_in"] == 1
    assert stats["total_out"] == 1


def test_t3_05_camera_cooldown_isolation_across_gates(auth_client, mock_db, freeze_clock):
    """T3-05: Cooldown on CAM_02_EXIT does not block immediate legitimate detection on CAM_01_ENTRY (2s delta)."""
    s = seed_test_student(mock_db, name="Turnaround Student", roll_number="GH-305", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 17, 0, 0, tzinfo=timezone.utc)) as clock:
        # Exit at CAM_02
        r1 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", s)
        assert r1 == "OUT"

        # Immediate turn-around 2 seconds later at CAM_01
        clock.tick(seconds=2.0)
        r2 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert r2 == "IN"

        logs = auth_client.get("/hostel/api/movement_logs?limit=5").get_json()["logs"]
        assert len(logs) == 2
        assert logs[0]["camera_id"] == "CAM_01_ENTRY"
        assert logs[1]["camera_id"] == "CAM_02_EXIT"


def test_t3_06_low_similarity_match_rpc_rejection_pipeline(auth_client, mock_db):
    """T3-06: Biometric similarity 0.32 (<0.40) rejected at RPC; state machine & movement logs untouched."""
    v_target = generate_unit_vector(512, seed=601)
    s = seed_test_student(mock_db, name="Enrolled Student", roll_number="GH-306", embedding=v_target, current_status="IN")

    # Generate candidate vector with similarity 0.32
    _, v_low = generate_calibrated_vector_pair(0.32, seed=602)

    matches = hostel_db.match_face_embedding(v_low, threshold=0.40)
    assert len(matches) == 0

    # Since no match found, state machine should not be invoked
    logs = auth_client.get("/hostel/api/movement_logs?limit=5").get_json()["logs"]
    assert len(logs) == 0

    # Status remains IN
    assert hostel_db.get_student_by_id(s["id"])["current_status"] == "IN"


def test_t3_07_exit_immediately_preceding_curfew_cutoff(auth_client, mock_db, freeze_clock):
    """T3-07: Student exits at 19:29:58; Curfew scanner at 19:30:00 catches student in overdue state."""
    s = seed_test_student(mock_db, name="Late Departure", roll_number="GH-307", current_status="IN")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 19, 29, 58, tzinfo=timezone.utc)) as clock:
        # Exit 2 seconds before cutoff
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"

        # 2 seconds later: 19:30:00 exact cutoff
        clock.set(datetime(2026, 9, 9, 19, 30, 0))
        curfew_service.check_curfew_violations()

        stats = auth_client.get("/hostel/api/stats").get_json()
        assert stats["overdue_count"] == 1

        alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["student_id"] == sid


def test_t3_08_resolved_alert_subsequent_outing_alert_cycle(auth_client, mock_db, freeze_clock):
    """T3-08: Resolved student leaves again during curfew; subsequent scan generates new overdue record."""
    s = seed_test_student(mock_db, name="Repeat Outing", roll_number="GH-308", current_status="OUT")
    sid = s["id"]

    with freeze_clock(datetime(2026, 9, 9, 19, 31, 0)) as clock:
        # Initial breach
        curfew_service.check_curfew_violations()
        alerts1 = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts1) == 1
        a1_id = alerts1[0]["id"]

        # Warden resolves alert 1 at 19:35
        clock.set(datetime(2026, 9, 9, 19, 35, 0))
        auth_client.post("/hostel/api/resolve_alert", json={"alert_id": a1_id, "notes": "Temporary pass"})
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0

        # Student re-enters at 19:36
        clock.set(datetime(2026, 9, 9, 19, 36, 0, tzinfo=timezone.utc))
        hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})

        # Student exits again without permission at 19:40
        clock.set(datetime(2026, 9, 9, 19, 40, 0, tzinfo=timezone.utc))
        hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"})

        # Subsequent scan at 19:42 generates new active alert
        clock.set(datetime(2026, 9, 9, 19, 42, 0))
        curfew_service.check_curfew_violations()

        alerts2 = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts2) == 1
        assert alerts2[0]["id"] != a1_id


def test_t3_09_multi_face_batch_detection_exit_overdue_sync(auth_client, mock_db, freeze_clock):
    """T3-09: Batch of 4 students exit together at 19:20; 19:30 curfew scanner detects all 4 in batch."""
    students = [
        seed_test_student(mock_db, name=f"Group {i}", roll_number=f"GH-GRP-{i}", current_status="IN")
        for i in range(4)
    ]

    with freeze_clock(datetime(2026, 9, 9, 19, 20, 0, tzinfo=timezone.utc)) as clock:
        # Batch exit at CAM_02_EXIT
        for s in students:
            res = hostel_state.process_student_detection(s["id"], "CAM_02_EXIT", s)
            assert res == "OUT"

        # Advance to 19:30:01
        clock.set(datetime(2026, 9, 9, 19, 30, 1))
        curfew_service.check_curfew_violations()

        stats = auth_client.get("/hostel/api/stats").get_json()
        assert stats["total_out"] == 4
        assert stats["overdue_count"] == 4

        alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts) == 4


def test_t3_10_schema_isolation_across_endpoints_and_engine(auth_client, mock_db, freeze_clock):
    """T3-10: 100% of queries across full workflow strictly target girls_hostel schema with 0 public leaks."""
    s = seed_test_student(mock_db, name="Schema Audit", roll_number="GH-AUDIT-01")

    # Workflow operations
    auth_client.get("/hostel/")
    auth_client.get("/hostel/api/stats")
    auth_client.get("/hostel/api/movement_logs")
    auth_client.get("/hostel/api/overdue_alerts")

    hostel_state.process_student_detection(s["id"], "CAM_02_EXIT", s)
    with freeze_clock(datetime(2026, 9, 9, 19, 35, 0)):
        curfew_service.check_curfew_violations()

    # Inspect all executed queries in mock DB
    for entry in mock_db.queries_log:
        if "table" in entry:
            table_name = entry["table"]
            assert "public" not in table_name, f"Forbidden public table access: {table_name}"
            assert table_name in MockSupabaseHostelClient.ALLOWED_TABLES or table_name in mock_db.tables
        if "rpc" in entry:
            rpc_name = entry["rpc"]
            assert "public" not in rpc_name, f"Forbidden public RPC: {rpc_name}"
