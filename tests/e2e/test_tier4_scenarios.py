"""
Tier 4: Real-World Operational Scenarios E2E Tests (BioSecure AI - Girls Hostel).
End-to-End temporal simulations modeling realistic hostel operations:
1. Friday Evening Rush & Curfew Breach (20 students, mass exit, safe returns, late arrivals, warden resolution)
2. Multi-Student Overdue Alert Batch Dispatch & Rapid Resolution (10 students, scanner idempotency, bulk review)
3. Morning Gate Congestion & Lingering (tailgating, face lingering on exit camera, 8 students)
4. 24-Hour Cycle System Window Transitions (Off-hours 14:00, Start 17:00, Cutoff 19:30, Midnight 01:00, Next-day reset)
5. High-Load Dual-Gate Burst Stress with Live Warden Dashboard Polling (50 detections, concurrent UI queries)
Total Tests: 5 (>=5 required).
"""

import concurrent.futures
import math
import threading
import time
from datetime import date, datetime, timedelta, timezone
import pytest

from src.utils import hostel_db, hostel_state
from src.services import curfew_service
from tests.helpers import (
    generate_unit_vector,
    seed_test_student,
)


def test_t4_01_friday_evening_rush_and_curfew_breach(auth_client, mock_db, freeze_clock):
    """
    T4-01: Friday Evening Rush & Curfew Breach Simulation.
    - 20 students enrolled, initially all IN.
    - Phase 1 (17:05 - 17:30): Mass exit of 15 students (S1-S15) via CAM_02_EXIT.
    - Phase 2 (18:30 - 19:25): Staggered safe return of 10 students (S1-S10) via CAM_01_ENTRY.
    - Phase 3 (19:30:01): Curfew cutoff scanner triggers 5 OVERDUE_OUT alerts for S11-S15.
    - Phase 4 (19:35): Warden reviews dashboard and parent contacts.
    - Phase 5 (19:40 - 19:45): Warden resolves 2 alerts (S11, S12); students arrive late and check IN.
    """
    # Cohort enrollment: 20 students
    students = [
        seed_test_student(
            mock_db,
            name=f"Student {i:02d}",
            roll_number=f"GH-2026-{i:03d}",
            room_number=f"A-{(i % 4) + 1}0{(i % 6) + 1}",
            parent_contact=f"+91-9876543{i:03d}",
            current_status="IN"
        )
        for i in range(1, 21)
    ]

    with freeze_clock(datetime(2026, 9, 11, 17, 0, 0, tzinfo=timezone.utc)) as clock:
        # Phase 1: 17:05 - 17:30 (Mass exit of students 1 to 15)
        for i in range(15):
            clock.tick(seconds=60.0)  # Staggered exits
            s = students[i]
            res = hostel_state.process_student_detection(s["id"], "CAM_02_EXIT", s)
            assert res == "OUT"

        stats1 = auth_client.get("/hostel/api/stats").get_json()
        assert stats1["total_students"] == 20
        assert stats1["total_in"] == 5
        assert stats1["total_out"] == 15
        assert stats1["overdue_count"] == 0

        # Phase 2: 18:30 - 19:25 (Safe returns of students 1 to 10)
        clock.set(datetime(2026, 9, 11, 18, 30, 0, tzinfo=timezone.utc))
        for i in range(10):
            clock.tick(seconds=120.0)
            s = students[i]
            res = hostel_state.process_student_detection(s["id"], "CAM_01_ENTRY", {"id": s["id"], "current_status": "OUT"})
            assert res == "IN"

        stats2 = auth_client.get("/hostel/api/stats").get_json()
        assert stats2["total_in"] == 15
        assert stats2["total_out"] == 5
        assert stats2["overdue_count"] == 0

        # Phase 3: 19:30:01 (Curfew Cutoff)
        clock.set(datetime(2026, 9, 11, 19, 30, 1))
        curfew_service.check_curfew_violations()

        stats3 = auth_client.get("/hostel/api/stats").get_json()
        assert stats3["total_in"] == 15
        assert stats3["total_out"] == 5
        assert stats3["overdue_count"] == 5

        # Phase 4: Warden reviews alerts
        alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts) == 5
        overdue_sids = {a["student_id"] for a in alerts}
        for i in range(10, 15):
            assert students[i]["id"] in overdue_sids
            # Verify parent contact presence
            matching_alert = next(a for a in alerts if a["student_id"] == students[i]["id"])
            assert matching_alert["student_profiles"]["parent_contact"] == students[i]["parent_contact"]

        # Phase 5: Warden resolves alerts for Student 11 and 12
        a_s11 = next(a for a in alerts if a["student_id"] == students[10]["id"])
        a_s12 = next(a for a in alerts if a["student_id"] == students[11]["id"])

        auth_client.post("/hostel/api/resolve_alert", json={
            "alert_id": a_s11["id"],
            "notes": "Parent confirmed train delay"
        })
        auth_client.post("/hostel/api/resolve_alert", json={
            "alert_id": a_s12["id"],
            "notes": "Bus delay verified"
        })

        # Overdue count decreases to 3
        stats4 = auth_client.get("/hostel/api/stats").get_json()
        assert stats4["overdue_count"] == 3

        # Late return of Student 11 and 12 at 19:45
        clock.set(datetime(2026, 9, 11, 19, 45, 0, tzinfo=timezone.utc))
        hostel_state.process_student_detection(students[10]["id"], "CAM_01_ENTRY", {"id": students[10]["id"], "current_status": "OUT"})
        hostel_state.process_student_detection(students[11]["id"], "CAM_01_ENTRY", {"id": students[11]["id"], "current_status": "OUT"})

        stats5 = auth_client.get("/hostel/api/stats").get_json()
        assert stats5["total_in"] == 17
        assert stats5["total_out"] == 3
        assert stats5["overdue_count"] == 3


def test_t4_02_multi_student_overdue_batch_dispatch_and_rapid_resolution(auth_client, mock_db, freeze_clock):
    """
    T4-02: Multi-Student Overdue Alert Batch Dispatch & Rapid Resolution.
    - 10 students seeded as OUT at 19:20.
    - Curfew scan at 19:30:00 generates 10 active alerts.
    - Consecutive scans at 19:31 and 19:32 prove alert deduplication idempotency.
    - Warden executes rapid sequential resolutions with custom notes.
    - Dashboard verifies overdue count returns to 0.
    """
    students = [
        seed_test_student(mock_db, name=f"Batch S{i}", roll_number=f"GH-BAT-{i:02d}", current_status="OUT")
        for i in range(10)
    ]

    with freeze_clock(datetime(2026, 9, 9, 19, 30, 0)) as clock:
        # Step 1: Initial curfew breach scan
        curfew_service.check_curfew_violations()

        alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts) == 10

        # Step 2: Idempotency verification over multiple subsequent scans
        clock.set(datetime(2026, 9, 9, 19, 31, 0))
        curfew_service.check_curfew_violations()
        clock.set(datetime(2026, 9, 9, 19, 32, 0))
        curfew_service.check_curfew_violations()

        # Alert count strictly preserved
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 10
        assert len(mock_db.tables["curfew_alerts"]) == 10

        # Step 3: Rapid sequential resolutions by warden
        for idx, alert in enumerate(alerts):
            notes = "Academic lab pass" if idx < 4 else "Parent contacted"
            resp = auth_client.post("/hostel/api/resolve_alert", json={
                "alert_id": alert["id"],
                "notes": notes
            })
            assert resp.status_code == 200

        # Step 4: Verification of clean dashboard state
        clean_alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(clean_alerts) == 0

        stats = auth_client.get("/hostel/api/stats").get_json()
        assert stats["overdue_count"] == 0


def test_t4_03_morning_rush_gate_congestion_and_lingering(auth_client, mock_db, freeze_clock):
    """
    T4-03: Morning Gate Congestion & Face Lingering Simulation.
    - 8 students exiting at 08:00 AM class rush.
    - Student 1 lingers in front of CAM_02_EXIT for 30s.
    - Cooldown debouncing suppresses repeated logs for Student 1.
    - Students 2 through 8 pass through in interleaved frames.
    - Cooldown expiry at 16s is debounced by pre-state guard (already OUT).
    - Total movement logs created equals exactly 8 (1 per student).
    """
    students = [
        seed_test_student(mock_db, name=f"Morning S{i}", roll_number=f"GH-MRN-{i}", current_status="IN")
        for i in range(1, 9)
    ]
    s1 = students[0]

    with freeze_clock(datetime(2026, 9, 9, 8, 0, 0, tzinfo=timezone.utc)) as clock:
        # Frame 1 (t0): Student 1 exits
        assert hostel_state.process_student_detection(s1["id"], "CAM_02_EXIT", s1) == "OUT"

        # Frames 2-6: Student 1 lingering in front of camera
        for sec in [2.0, 5.0, 8.0, 11.0, 14.0]:
            clock.set(datetime(2026, 9, 9, 8, 0, int(sec), tzinfo=timezone.utc))
            res = hostel_state.process_student_detection(s1["id"], "CAM_02_EXIT", {"id": s1["id"], "current_status": "OUT"})
            assert res is None, f"Lingering read at {sec}s should be suppressed"

        # Interspersed frames: Students 2-8 pass through
        for idx in range(1, 8):
            s = students[idx]
            clock.tick(seconds=0.5)
            res = hostel_state.process_student_detection(s["id"], "CAM_02_EXIT", s)
            assert res == "OUT"

        # Frame 14 (t0 + 16s): Student 1 still standing in front of lens
        clock.set(datetime(2026, 9, 9, 8, 0, 16, tzinfo=timezone.utc))
        res_lingering = hostel_state.process_student_detection(s1["id"], "CAM_02_EXIT", {"id": s1["id"], "current_status": "OUT"})
        # Student 1 is already OUT, so pre-state debouncing handles cleanly
        assert res_lingering == "OUT"

        # Verification: Exactly 8 movement logs exist (1 per student)
        logs = auth_client.get("/hostel/api/movement_logs?limit=50").get_json()["logs"]
        assert len(logs) == 8

        # All 8 students have status OUT
        all_students = hostel_db.fetch_all_hostel_students()
        assert all(s["current_status"] == "OUT" for s in all_students)


def test_t4_04_full_24hr_cycle_system_window_transitions(auth_client, mock_db, freeze_clock):
    """
    T4-04: 24-Hour Cycle System Window Transitions.
    - 14:00 (Daytime off-hours): Exit permitted, curfew scanner inactive.
    - 17:00 (Curfew window open): Standard evening window, outings permitted without alerts.
    - 19:29:59 (1s before cutoff): Scan produces 0 alerts.
    - 19:30:01 (Cutoff): Scan generates alert for Date 1.
    - 01:00 (Post-midnight active curfew): Scanner continues active enforcement.
    - 06:15 (Next morning Date 2): Student returns and checks IN.
    - 19:30 (Date 2 evening cutoff): Scanner runs and confirms zero alerts for new day.
    """
    s = seed_test_student(mock_db, name="Full Cycle Student", roll_number="GH-CYCLE-01", current_status="IN")
    sid = s["id"]

    # 1. 14:00 (Off-Hours)
    with freeze_clock(datetime(2026, 9, 9, 14, 0, 0, tzinfo=timezone.utc)) as clock:
        hostel_state.process_student_detection(sid, "CAM_02_EXIT", s)
        curfew_service.check_curfew_violations()
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0

        # 2. 17:00 (System start time)
        clock.set(datetime(2026, 9, 9, 17, 0, 0))
        curfew_service.check_curfew_violations()
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0

        # 3. 19:29:59 (Boundary)
        clock.set(datetime(2026, 9, 9, 19, 29, 59))
        curfew_service.check_curfew_violations()
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0

        # 4. 19:30:01 (Cutoff - Overdue Alert Generated)
        clock.set(datetime(2026, 9, 9, 19, 30, 1))
        curfew_service.check_curfew_violations()
        alerts1 = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(alerts1) == 1
        assert alerts1[0]["curfew_date"] == "2026-09-09"

        # 5. 01:00 AM (Post-Midnight Active Curfew)
        clock.set(datetime(2026, 9, 10, 1, 0, 0))
        curfew_service.check_curfew_violations()
        # Remains in active curfew enforcement
        night_alerts = auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]
        assert len(night_alerts) >= 1

        # 6. Next Morning 06:15 AM (Date 2 Re-entry)
        clock.set(datetime(2026, 9, 10, 6, 15, 0, tzinfo=timezone.utc))
        hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert hostel_db.get_student_by_id(sid)["current_status"] == "IN"

        # Warden resolves active overdue alerts
        for a in night_alerts:
            auth_client.post("/hostel/api/resolve_alert", json={
                "alert_id": a["id"],
                "notes": "Returned morning 06:15"
            })

        # 7. Next Evening Cutoff at 19:30 (Date 2)
        clock.set(datetime(2026, 9, 10, 19, 30, 5))
        curfew_service.check_curfew_violations()
        # Student is IN, so zero alerts for Date 2
        assert len(auth_client.get("/hostel/api/overdue_alerts").get_json()["alerts"]) == 0


def test_t4_05_high_load_dual_gate_burst_with_concurrent_warden_polling(auth_client, mock_db):
    """
    T4-05: High-Load Dual-Gate Burst Stress Simulation with Concurrent Dashboard Polling.
    - 20 students enrolled.
    - 50 rapid detection events across Entry and Exit gates in a multi-threaded pool.
    - Concurrently, 3 dashboard polling threads repeatedly query stats, movement logs, and overdue alerts.
    - Verifies zero 500 exceptions, database consistency, and atomic total_students == total_in + total_out invariant.
    """
    students = [
        seed_test_student(mock_db, name=f"Stress S{i}", roll_number=f"GH-STR-{i:02d}", current_status="IN")
        for i in range(20)
    ]

    stop_polling = threading.Event()
    polling_errors = []
    stats_snapshots = []

    def poll_dashboard():
        while not stop_polling.is_set():
            try:
                r_stats = auth_client.get("/hostel/api/stats")
                assert r_stats.status_code == 200
                data = r_stats.get_json()
                stats_snapshots.append(data)

                r_logs = auth_client.get("/hostel/api/movement_logs?limit=20")
                assert r_logs.status_code == 200

                r_alerts = auth_client.get("/hostel/api/overdue_alerts")
                assert r_alerts.status_code == 200
            except Exception as exc:
                polling_errors.append(exc)
            time.sleep(0.01)

    # Start 3 concurrent polling threads
    pollers = [threading.Thread(target=poll_dashboard, daemon=True) for _ in range(3)]
    for p in pollers:
        p.start()

    # Generate 50 rapid detection events across threads
    def trigger_detection(idx):
        s = students[idx % len(students)]
        cam = "CAM_02_EXIT" if idx % 2 == 0 else "CAM_01_ENTRY"
        return hostel_state.process_student_detection(s["id"], cam, s)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(trigger_detection, i) for i in range(50)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Stop polling threads
    time.sleep(0.05)
    stop_polling.set()
    for p in pollers:
        p.join(timeout=2.0)

    # Assertions
    assert len(polling_errors) == 0, f"Dashboard polling encountered errors: {polling_errors}"
    assert len(stats_snapshots) > 0, "No stats snapshots captured"

    # Verify atomic invariant across all polling snapshots
    for snapshot in stats_snapshots:
        assert snapshot["total_students"] == snapshot["total_in"] + snapshot["total_out"], (
            f"Headcount invariant broken in snapshot: {snapshot}"
        )
