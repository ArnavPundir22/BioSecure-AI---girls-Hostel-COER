"""
Adversarial Stress Test Suite: Biometrics & Movement Cooldown.
Challenger 1 (E2E Adversarial Verifier).

Coverage:
1. Floating Point Vector Boundaries:
   - Exact boundary 0.39999 (rejected) vs 0.40000 (accepted) vs 0.40001 (accepted).
   - High precision floating point ranking & tie-break behavior.
   - Non-normalized vectors: norm >> 1 (norm=10.0, norm=100.0), norm << 1 (norm=0.01, norm=1e-5).
   - Zero vectors (norm=0.0) and subnormal near-zero vectors (norm=1e-18).
   - Orthogonal vectors (similarity = 0.0) and strictly antipodal vectors (similarity = -1.0).
   - NaN and Inf vectors in query and database.
   - Embedding dimension mismatches (511D, 513D, empty, None).
   - In-memory face_cache batch matching with non-normalized and edge vectors.
   - Noise amplification vulnerability test on subnormal/tiny norm vectors.

2. Microsecond Timing Boundaries & Movement Cooldown:
   - Cooldown rejection at 14.899s (t0 + 14.899s rejected).
   - Microsecond edge at 14.999999s (rejected).
   - Exact boundary at 15.000000s (accepted).
   - Microsecond acceptance at 15.000001s (accepted).
   - Cooldown acceptance at 15.001s (accepted).
   - Cooldown window preservation: repeated suppressed detections do NOT prolong cooldown.
   - Single-student rapid burst: 50 detections in 10ms produce exactly 1 log and 49 suppressions.
   - Multi-student concurrent burst: 10 different students at the exact same microsecond.
   - Cross-camera rapid transitions & U-turn: exit CAM_02 at t0, entry CAM_01 at t0+100ms.
   - Cross-camera rapid ping-pong attack: verify camera-specific cooldown prevents oscillation flood.
   - Multi-threaded concurrent detection race condition stress test on movement engine.
"""

import math
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import List
import numpy as np
import pytest

from src.utils import hostel_db, hostel_state, face_cache
from src.utils.face import normalize_embedding
from tests.helpers import (
    generate_calibrated_vector_pair,
    generate_vector_with_similarity_to,
    generate_unit_vector,
    seed_test_student,
)


# ============================================================================
# PART 1: Floating Point Vector Boundaries
# ============================================================================

def test_adv_vector_exact_threshold_039999_vs_040001(mock_db):
    """
    Adversarial 1.1: Exact threshold boundary discrimination.
    Similarity 0.39999 must NOT match threshold 0.40000.
    Similarity 0.40000 must match.
    Similarity 0.40001 must match.
    """
    v_query = generate_unit_vector(512, seed=9001)

    v_below = generate_vector_with_similarity_to(v_query, 0.39999, seed=9002)
    v_exact = generate_vector_with_similarity_to(v_query, 0.40000, seed=9003)
    v_above = generate_vector_with_similarity_to(v_query, 0.40001, seed=9004)

    s_below = seed_test_student(mock_db, name="Below 0.39999", roll_number="ADV-V01", embedding=v_below)
    s_exact = seed_test_student(mock_db, name="Exact 0.40000", roll_number="ADV-V02", embedding=v_exact)
    s_above = seed_test_student(mock_db, name="Above 0.40001", roll_number="ADV-V03", embedding=v_above)

    matches = hostel_db.match_face_embedding(v_query, threshold=0.40000, count=10)
    matched_ids = [m["id"] for m in matches]

    assert s_below["id"] not in matched_ids, "Candidate with 0.39999 similarity must NOT match threshold 0.40"
    assert s_exact["id"] in matched_ids, "Candidate with exact 0.40000 similarity must match threshold 0.40"
    assert s_above["id"] in matched_ids, "Candidate with 0.40001 similarity must match threshold 0.40"


def test_adv_vector_non_normalized_queries_and_embeddings(mock_db):
    """
    Adversarial 1.2: Non-normalized vectors (norm >> 1 and norm << 1).
    Cosine similarity is invariant under positive scalar multiplication.
    v_query * 100.0 and v_target * 0.01 must produce identical cosine similarity to unit vectors.
    """
    v1_unit, v2_unit = generate_calibrated_vector_pair(0.85, seed=9101)

    # Scale target embedding by 50.0 (non-unit)
    v2_scaled_up = [x * 50.0 for x in v2_unit]
    s1 = seed_test_student(mock_db, name="Scaled Up Embedding", roll_number="ADV-V10", embedding=v2_scaled_up)

    # Scale query vector by 0.005 (non-unit, small norm)
    v1_scaled_down = [x * 0.005 for x in v1_unit]

    matches = hostel_db.match_face_embedding(v1_scaled_down, threshold=0.40, count=5)
    assert len(matches) == 1
    assert matches[0]["id"] == s1["id"]
    # Mathematically, cosine similarity should still be ~0.85
    assert math.isclose(matches[0]["similarity"], 0.85, abs_tol=1e-3)


def test_adv_vector_zero_and_subnormal_vectors(mock_db):
    """
    Adversarial 1.3: Zero vectors and subnormal near-zero vectors.
    Must return empty matches gracefully without ZeroDivisionError or crash.
    """
    v_zero = [0.0] * 512
    v_subnormal = [1e-18] * 512

    # Normal student in database
    v_normal = generate_unit_vector(512, seed=9201)
    s_normal = seed_test_student(mock_db, name="Normal Student", roll_number="ADV-V20", embedding=v_normal)

    # Zero embedding student
    s_zero = seed_test_student(mock_db, name="Zero Vector Student", roll_number="ADV-V21", embedding=v_zero)

    # 1. Normal query against zero vector in DB: zero vector must not match
    matches_normal = hostel_db.match_face_embedding(v_normal, threshold=0.40, count=5)
    assert len(matches_normal) == 1
    assert matches_normal[0]["id"] == s_normal["id"]

    # 2. Query with zero vector: must return empty list without crash
    matches_from_zero = hostel_db.match_face_embedding(v_zero, threshold=0.40, count=5)
    assert matches_from_zero == [], "Zero query vector must yield empty match list without error"

    # 3. Query with subnormal noise vector against normal DB students: must return empty list (<0.40)
    matches_from_sub = hostel_db.match_face_embedding(v_subnormal, threshold=0.40, count=5)
    assert matches_from_sub == [], "Subnormal query vector must not match normal student profile"


def test_adv_vector_orthogonal_and_antipodal_extreme_cosines(mock_db):
    """
    Adversarial 1.4: Extreme cosine values (orthogonal = 0.0, antipodal = -1.0, identical = 1.0).
    Calibrated directly against base query vector.
    """
    v_base = generate_unit_vector(512, seed=9301)
    # Strictly antipodal vector: exactly -v_base
    v_anti = [-x for x in v_base]
    # Orthogonal vector relative to v_base
    v_ortho = generate_vector_with_similarity_to(v_base, 0.0, seed=9302)
    v_near_ortho_pos = generate_vector_with_similarity_to(v_base, 0.0001, seed=9303)
    v_near_ortho_neg = generate_vector_with_similarity_to(v_base, -0.0001, seed=9304)

    s_base = seed_test_student(mock_db, name="Base Student", roll_number="ADV-V29", embedding=v_base)
    s_ortho = seed_test_student(mock_db, name="Ortho", roll_number="ADV-V30", embedding=v_ortho)
    s_anti = seed_test_student(mock_db, name="Anti", roll_number="ADV-V31", embedding=v_anti)
    s_pos = seed_test_student(mock_db, name="Near Ortho Pos", roll_number="ADV-V32", embedding=v_near_ortho_pos)
    s_neg = seed_test_student(mock_db, name="Near Ortho Neg", roll_number="ADV-V33", embedding=v_near_ortho_neg)

    # Query with v_base at standard threshold 0.40:
    # Only s_base matches (~1.0). Ortho, near ortho, and antipodal must be excluded.
    matches = hostel_db.match_face_embedding(v_base, threshold=0.40, count=10)
    assert len(matches) == 1
    assert matches[0]["id"] == s_base["id"]

    # Query with threshold -0.50:
    # s_base (1.0), s_ortho (0.0), s_pos (0.0001), s_neg (-0.0001) must match.
    # s_anti (-1.0) must be strictly excluded because -1.0 < -0.50.
    matches_low = hostel_db.match_face_embedding(v_base, threshold=-0.50, count=10)
    matched_ids_low = [m["id"] for m in matches_low]
    assert s_base["id"] in matched_ids_low
    assert s_ortho["id"] in matched_ids_low
    assert s_pos["id"] in matched_ids_low
    assert s_neg["id"] in matched_ids_low
    assert s_anti["id"] not in matched_ids_low, "Antipodal vector (-1.0) must NOT match threshold -0.50"


def test_adv_vector_nan_and_infinity_resilience(mock_db):
    """
    Adversarial 1.5: NaN and Infinite floats in embeddings must not crash or poison the matcher.
    """
    v_nan = [float("nan")] * 512
    v_inf = [float("inf")] * 512

    s_nan = seed_test_student(mock_db, name="NaN Student", roll_number="ADV-V40", embedding=v_nan)
    s_inf = seed_test_student(mock_db, name="Inf Student", roll_number="ADV-V41", embedding=v_inf)

    v_normal = generate_unit_vector(512, seed=9401)
    s_normal = seed_test_student(mock_db, name="Normal Student", roll_number="ADV-V42", embedding=v_normal)

    # Query with normal vector: NaN and Inf students must be safely skipped
    matches = hostel_db.match_face_embedding(v_normal, threshold=0.40, count=5)
    assert len(matches) == 1
    assert matches[0]["id"] == s_normal["id"]

    # Query with NaN vector: must return empty list safely
    matches_nan = hostel_db.match_face_embedding(v_nan, threshold=0.40, count=5)
    assert matches_nan == []

    # Query with Inf vector: must return empty list safely
    matches_inf = hostel_db.match_face_embedding(v_inf, threshold=0.40, count=5)
    assert matches_inf == []


def test_adv_face_cache_batch_matcher_stress():
    """
    Adversarial 1.6: In-memory BLAS matrix matcher face_cache.match_faces_batch stress.
    Tests normalization helper and batch matching with non-normalized, zero, and edge arrays.
    """
    # Test normalize_embedding helper
    arr_zero = np.zeros(512, dtype=np.float32)
    assert normalize_embedding(arr_zero) is None

    arr_scaled = np.ones(512, dtype=np.float32) * 2.0
    normed = normalize_embedding(arr_scaled)
    assert normed is not None
    assert math.isclose(float(np.linalg.norm(normed)), 1.0, abs_tol=1e-5)

    # Populate in-memory face cache
    v_normed1 = normalize_embedding(np.array(generate_unit_vector(512, seed=9501), dtype=np.float32))
    v_normed2 = normalize_embedding(np.array(generate_unit_vector(512, seed=9502), dtype=np.float32))
    
    face_cache.add_student_to_cache(
        student_id="STU-CACHE-01",
        name="Cache Student 1",
        program="B.Tech",
        branch="CSE",
        embedding=v_normed1
    )
    face_cache.add_student_to_cache(
        student_id="STU-CACHE-02",
        name="Cache Student 2",
        program="B.Tech",
        branch="ECE",
        embedding=v_normed2
    )

    # Match queries: exact match, non-normalized match, zero vector match, unrelated match
    q_exact = v_normed1
    q_scaled = v_normed1 * 42.0  # un-normalized query
    q_zero = np.zeros(512, dtype=np.float32)
    q_unrelated = np.array(generate_unit_vector(512, seed=9599), dtype=np.float32)

    results = face_cache.match_faces_batch(
        [q_exact, q_scaled, q_zero, q_unrelated],
        match_threshold=0.40
    )

    assert len(results) == 4
    # Query 0: Exact match
    assert results[0] is not None
    assert results[0]["id"] == "STU-CACHE-01"
    assert math.isclose(results[0]["similarity"], 1.0, abs_tol=1e-4)

    # Query 1: Scaled query (should auto-normalize and match)
    assert results[1] is not None
    assert results[1]["id"] == "STU-CACHE-01"
    assert math.isclose(results[1]["similarity"], 1.0, abs_tol=1e-4)

    # Query 2: Zero vector (normalized to None, should yield None)
    assert results[2] is None

    # Query 3: Unrelated vector (similarity < 0.40, should yield None)
    assert results[3] is None


# ============================================================================
# PART 2: Microsecond Timing Boundaries & Movement Cooldown
# ============================================================================

def test_adv_cooldown_microsecond_boundary_14_899_vs_15_001(mock_db, freeze_clock):
    """
    Adversarial 2.1: Precise timing boundary evaluation at sub-second and microsecond resolution:
    - t0 + 14.899s: REJECTED (< 15.0s)
    - t0 + 14.999999s: REJECTED (< 15.0s)
    - t0 + 15.000000s: ACCEPTED (== 15.0s)
    - t0 + 15.000001s: ACCEPTED (> 15.0s)
    - t0 + 15.001s: ACCEPTED (> 15.0s)
    """
    s = seed_test_student(mock_db, name="Microsecond Student", roll_number="ADV-T01", current_status="IN")
    sid = s["id"]
    t0 = datetime(2026, 9, 9, 17, 0, 0, 0, tzinfo=timezone.utc)

    # Test 14.899s and 14.999999s boundary (rejection)
    with freeze_clock(t0) as clock:
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1

        # Advance to 14.899s: rejected
        clock.set(t0 + timedelta(seconds=14, milliseconds=899))
        res_14_899 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "OUT"})
        assert res_14_899 is None, "Detection at 14.899s must be suppressed by cooldown"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1

        # Advance to 14.999999s (1 microsecond before 15s): rejected
        clock.set(t0 + timedelta(seconds=14, microseconds=999999))
        res_micro_pre = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "OUT"})
        assert res_micro_pre is None, "Detection at 14.999999s must be suppressed by cooldown"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 1

    # Reset cooldown registry for exact 15.000000s check
    hostel_state._cooldown_registry.clear()
    mock_db.tables["movement_logs"].clear()

    # Test 15.000000s exact boundary: accepted
    with freeze_clock(t0) as clock:
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"
        clock.set(t0 + timedelta(seconds=15, microseconds=0))
        res_exact = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert res_exact == "IN", "Detection at exact 15.000000s must be accepted"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 2

    # Reset for 15.000001s check
    hostel_state._cooldown_registry.clear()
    mock_db.tables["movement_logs"].clear()

    # Test 15.000001s microsecond post boundary: accepted
    with freeze_clock(t0) as clock:
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"
        clock.set(t0 + timedelta(seconds=15, microseconds=1))
        res_post_micro = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert res_post_micro == "IN", "Detection at 15.000001s must be accepted"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 2

    # Reset for 15.001s check
    hostel_state._cooldown_registry.clear()
    mock_db.tables["movement_logs"].clear()

    # Test 15.001s boundary: accepted
    with freeze_clock(t0) as clock:
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"
        clock.set(t0 + timedelta(seconds=15, milliseconds=1))
        res_15_001 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert res_15_001 == "IN", "Detection at 15.001s must be accepted"
        assert len(hostel_db.fetch_recent_movement_logs(limit=5)) == 2


def test_adv_cooldown_window_not_extended_by_suppressed_reads(mock_db, freeze_clock):
    """
    Adversarial 2.2: Verify suppressed reads do NOT reset or extend the 15s cooldown clock.
    If a student constantly moves in front of the camera at t0+2s, t0+5s, t0+10s, t0+14s,
    the cooldown MUST STILL expire at t0 + 15.0s, NOT t0 + 14s + 15s.
    """
    s = seed_test_student(mock_db, name="Loitering Student", roll_number="ADV-T02", current_status="IN")
    sid = s["id"]
    t0 = datetime(2026, 9, 9, 17, 0, 0, tzinfo=timezone.utc)

    with freeze_clock(t0) as clock:
        # t0: Initial exit event
        assert hostel_state.process_student_detection(sid, "CAM_02_EXIT", s) == "OUT"

        # Continuous detections throughout the cooldown window
        for sec in [2.0, 5.0, 8.0, 11.0, 14.0, 14.9]:
            clock.set(t0 + timedelta(seconds=sec))
            res = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "OUT"})
            assert res is None, f"Detection at t0+{sec}s must be suppressed"

        # At t0 + 15.1s, the cooldown MUST have expired relative to t0
        clock.set(t0 + timedelta(seconds=15, milliseconds=100))
        res_after = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert res_after == "IN", "Cooldown must expire at t0+15s regardless of intervening suppressed reads"
        assert len(hostel_db.fetch_recent_movement_logs(limit=10)) == 2


def test_adv_rapid_burst_50_detections_in_10ms(mock_db, freeze_clock):
    """
    Adversarial 2.3: Single-student high-density rapid burst (50 reads in 10 milliseconds).
    Must result in exactly 1 state transition and 1 movement log.
    The subsequent 49 burst detections must all return None.
    """
    s = seed_test_student(mock_db, name="Burst Face", roll_number="ADV-T03", current_status="IN")
    sid = s["id"]
    t0 = datetime(2026, 9, 9, 17, 0, 0, 0, tzinfo=timezone.utc)

    with freeze_clock(t0) as clock:
        results = []
        for i in range(50):
            # Advance 200 microseconds per iteration (10ms total across 50 iterations)
            clock.set(t0 + timedelta(microseconds=i * 200))
            r = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"})
            results.append(r)

        assert results[0] == "OUT", "First detection of burst must succeed"
        assert all(r is None for r in results[1:]), "All 49 subsequent reads in burst must be suppressed"
        logs = hostel_db.fetch_recent_movement_logs(limit=100)
        assert len(logs) == 1, "Only exactly 1 movement log should be created for the burst"


def test_adv_multi_student_simultaneous_microsecond_burst(mock_db, freeze_clock):
    """
    Adversarial 2.4: 10 different students detected simultaneously at the EXACT SAME microsecond.
    Every student must successfully transition with zero cross-talk, resulting in 10 unique logs.
    """
    students = [
        seed_test_student(mock_db, name=f"Group Student {i}", roll_number=f"ADV-GRP-{i:02d}", current_status="IN")
        for i in range(10)
    ]
    t_fixed = datetime(2026, 9, 9, 17, 15, 0, 123456, tzinfo=timezone.utc)

    with freeze_clock(t_fixed):
        results = []
        for s in students:
            res = hostel_state.process_student_detection(s["id"], "CAM_02_EXIT", s)
            results.append(res)

        assert all(r == "OUT" for r in results), "All 10 students must be allowed through simultaneously"
        logs = hostel_db.fetch_recent_movement_logs(limit=50)
        assert len(logs) == 10, "10 separate movement logs must be recorded"
        logged_sids = {log["student_id"] for log in logs}
        assert len(logged_sids) == 10, "All 10 student IDs must be present in the logs"


def test_adv_cross_camera_rapid_u_turn(mock_db, freeze_clock):
    """
    Adversarial 2.5: Cross-camera rapid transition (U-turn scenario).
    Student exits at CAM_02_EXIT at t0, then immediately enters at CAM_01_ENTRY at t0 + 100ms.
    Verification:
    1. Exit on CAM_02 is recorded (state -> OUT).
    2. Entry on CAM_01 at 100ms is allowed (state -> IN), because CAM_01 cooldown is distinct from CAM_02.
    3. Immediate re-trigger on CAM_02 at 200ms is BLOCKED (CAM_02 cooldown active until t0+15s).
    4. Immediate re-trigger on CAM_01 at 300ms is BLOCKED (CAM_01 cooldown active until t0+15.1s).
    """
    s = seed_test_student(mock_db, name="U-Turn Student", roll_number="ADV-T05", current_status="IN")
    sid = s["id"]
    t0 = datetime(2026, 9, 9, 17, 30, 0, 0, tzinfo=timezone.utc)

    with freeze_clock(t0) as clock:
        # 1. Exit on CAM_02 at t0
        r1 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", s)
        assert r1 == "OUT"

        # 2. U-turn into CAM_01 at t0 + 100ms
        clock.set(t0 + timedelta(milliseconds=100))
        r2 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert r2 == "IN", "U-turn on entry camera must be accepted"

        # 3. CAM_02 detects student again at t0 + 200ms (loitering between gates)
        clock.set(t0 + timedelta(milliseconds=200))
        r3 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"})
        assert r3 is None, "CAM_02 must reject detection because 200ms < 15s cooldown"

        # 4. CAM_01 detects student again at t0 + 300ms
        clock.set(t0 + timedelta(milliseconds=300))
        r4 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "IN"})
        assert r4 is None, "CAM_01 must reject detection because 200ms elapsed < 15s cooldown"

        logs = hostel_db.fetch_recent_movement_logs(limit=10)
        assert len(logs) == 2, "Exactly 2 movements (OUT then IN) should be logged"
        assert logs[0]["direction"] == "IN"
        assert logs[1]["direction"] == "OUT"


def test_adv_cross_camera_ping_pong_attack(mock_db, freeze_clock):
    """
    Adversarial 2.6: High-frequency alternating camera attack (ping-pong between CAM_01 and CAM_02).
    Attempt to alternate detections every 200ms for 20 cycles.
    Verify the system does NOT create 40 movement logs, but strictly bounds transitions:
    Cycle 0: CAM_02 (OUT) -> logged. CAM_02 on cooldown for 15s.
    Cycle 0: CAM_01 (IN)  -> logged. CAM_01 on cooldown for 15s.
    Subsequent cycles < 15s: both cameras are in active cooldown, zero additional logs.
    At t0 + 15.1s: CAM_02 (OUT) -> logged.
    At t0 + 15.3s: CAM_01 (IN)  -> logged.
    """
    s = seed_test_student(mock_db, name="PingPong Student", roll_number="ADV-T06", current_status="IN")
    sid = s["id"]
    t0 = datetime(2026, 9, 9, 18, 0, 0, 0, tzinfo=timezone.utc)

    with freeze_clock(t0) as clock:
        # Rapidly alternate between CAM_02 and CAM_01 every 200ms for 5 seconds (25 attempts each)
        for i in range(25):
            clock.set(t0 + timedelta(milliseconds=i * 200))
            cam = "CAM_02_EXIT" if i % 2 == 0 else "CAM_01_ENTRY"
            target_status = "IN" if cam == "CAM_02_EXIT" else "OUT"
            hostel_state.process_student_detection(sid, cam, {"id": sid, "current_status": target_status})

        logs_initial = hostel_db.fetch_recent_movement_logs(limit=50)
        # Should only have logged the first CAM_02_EXIT and first CAM_01_ENTRY!
        assert len(logs_initial) == 2, f"Rapid ping-pong must be capped at 2 transitions; got {len(logs_initial)}"

        # Now advance past the 15s cooldown to t0 + 15.5s
        clock.set(t0 + timedelta(seconds=15, milliseconds=500))
        r_exit2 = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"})
        assert r_exit2 == "OUT", "CAM_02 detection past 15s must be permitted"

        clock.set(t0 + timedelta(seconds=15, milliseconds=700))
        r_entry2 = hostel_state.process_student_detection(sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"})
        assert r_entry2 == "IN", "CAM_01 detection past 15s must be permitted"

        logs_final = hostel_db.fetch_recent_movement_logs(limit=50)
        assert len(logs_final) == 4


def test_adv_concurrent_multithreaded_movement_stress(mock_db):
    """
    Adversarial 2.7: Multi-threaded race condition stress test.
    Spawn 10 concurrent threads all calling process_student_detection simultaneously
    for the SAME student on CAM_02_EXIT.
    Verify whether the system remains stable and does not produce corrupt entries.
    """
    s = seed_test_student(mock_db, name="Thread Race Student", roll_number="ADV-T07", current_status="IN")
    sid = s["id"]

    results = []
    errors = []
    barrier = threading.Barrier(10)

    def worker():
        try:
            barrier.wait()  # synchronize release
            res = hostel_state.process_student_detection(sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"})
            results.append(res)
        except Exception as ex:
            errors.append(ex)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent execution raised unexpected errors: {errors}"
    assert len(results) == 10
    # In a race condition without locks, multiple threads might get through before the first sets cooldown.
    # At least one thread must have succeeded.
    successful_outs = [r for r in results if r == "OUT"]
    assert len(successful_outs) >= 1, "At least one concurrent detection must have succeeded"
    logs = hostel_db.fetch_recent_movement_logs(limit=20)
    assert len(logs) >= 1
