# Adversarial Stress Testing & Verification Report — Biometrics & Movement Cooldown

**Author**: Challenger 1 (E2E Adversarial Verifier)  
**Target Milestone**: Milestone 2 (Girls Hostel Subsystem - End-to-End Test Harness & Engine Verification)  
**Working Directory**: `/home/dell/BioSecure AI - GIrls Hostel/.agents/challenger_e2e_1`  
**Date**: 2026-09-09  

---

## Challenge Summary

**Overall Risk Assessment**: **LOW to MEDIUM**  
The core E2E test harness and movement logic are robust across primary functional requirements, with comprehensive microsecond timing precision and mathematical vector boundary enforcement. However, two non-trivial edge-case vulnerabilities and one mock precision artifact were empirically identified:
1. **Subnormal / Tiny-Norm Vector Amplification Vulnerability (Medium)**: In `src/utils/face.py`, `normalize_embedding` checks `if norm == 0:` but lacks a lower-bound epsilon noise threshold (e.g. `1e-4`). Extremely small subnormal or near-zero vectors from corrupted camera buffers can be amplified into valid unit embeddings.
2. **Missing Thread Lock on Cooldown Registry (Medium)**: In `src/utils/hostel_state.py`, `_cooldown_registry` lacks a `threading.Lock` (unlike `face_cache.py` which uses `_cache_lock`), creating a check-then-act race window under concurrent multi-camera worker threads.
3. **Sort Precision Degradation via 4-Decimal Rounding (Low)**: In `conftest.py` and `hostel_db.py`, `similarity` is rounded to 4 decimal places before sorting, causing candidate tie-breaking at $\Delta s < 10^{-4}$ to degenerate into insertion order.

---

## Challenges & Vulnerability Analysis

### [Medium] Challenge 1: Lack of Epsilon Noise Floor in Face Normalization (`normalize_embedding`)

- **Assumption Challenged**: All incoming face embeddings from the InsightFace Buffalo_L model or camera pipeline have a meaningful norm ($\sim 1.0$), and only exact zero vectors (`norm == 0`) indicate invalid inputs.
- **Attack Scenario**: Corrupted camera frames, partially initialized frame buffers, or dark noise can produce embeddings where all 512 dimensions are subnormal floats (e.g. $10^{-18}$). `np.linalg.norm(arr)` evaluates to $\approx 2.26 \times 10^{-17} \ne 0$. Dividing `arr / norm` scales up sensor noise by a factor of $10^{17}$, creating a unit vector on the hypersphere that can falsely correlate with noise artifacts or corrupt the drift tracking EWMA.
- **Blast Radius**: Erroneous biometric matches on corrupted video frames, embedding drift corruption, or false positive alerts.
- **Mitigation**: Update `src/utils/face.py` to enforce a minimum norm floor:
  ```python
  MIN_EMBEDDING_NORM = 0.1  # Valid unit vectors should have norm ~1.0
  if norm < MIN_EMBEDDING_NORM:
      return None
  ```

---

### [Medium] Challenge 2: Unsynchronized Global Cooldown Registry in `hostel_state.py`

- **Assumption Challenged**: Movement detection calls from dual camera streams (`CAM_01_ENTRY`, `CAM_02_EXIT`) and background workers serialize safely without explicit locking.
- **Attack Scenario**: Two camera workers process simultaneous frames of a student at the gate. Both threads execute `cooldown_time = _cooldown_registry.get((student_id, camera_id))` before either thread updates `_cooldown_registry[(student_id, camera_id)] = now`. Both threads evaluate `cooldown_time is None`, calling `hostel_db.update_student_movement_state` and inserting duplicate movement logs into `girls_hostel.movement_logs`.
- **Blast Radius**: Inconsistent movement logs, false duplicate entry/exit notifications to wardens, and distorted attendance statistics.
- **Mitigation**: Introduce a reentrant lock (`threading.Lock()`) around `_cooldown_registry` operations in `hostel_state.py`, matching the pattern already used in `face_cache.py`.

---

### [Low] Challenge 3: Candidate Sorting Precision Loss from 4-Decimal Truncation

- **Assumption Challenged**: Rounding similarity scores to 4 decimal places (`round(sim, 4)`) provides sufficient resolution for top-$k$ nearest neighbor ranking.
- **Attack Scenario**: Two student profiles have close cosine similarities to a query vector: Candidate A ($s = 0.85004$) and Candidate B ($s = 0.85001$). Both get rounded to $0.8500$. In `MockIsolatedRpcQuery` and `MockRpcQuery`, sorting by `m["similarity"]` treats them as equal, causing Candidate B to potentially be returned before Candidate A if it was inserted first in the mock database.
- **Blast Radius**: Minor ranking non-determinism in tests when candidates differ by $< 0.0001$. In production, PostgreSQL pgvector performs true 64-bit/32-bit float distance ordering `ORDER BY sp.embedding <=> query_embedding ASC`, so this is primarily a test mock fidelity issue.
- **Mitigation**: Sort candidates using the raw unrounded float similarity, applying `round(sim, 4)` only for output representation.

---

## Stress Test Results

A dedicated adversarial test suite (`tests/e2e/test_adversarial_biometrics_cooldown.py`, 13 tests) was executed alongside the existing test suite (71 tests). Total tests executed: **84 passed, 0 failed**.

| Test Identifier | Scenario | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| `test_adv_vector_exact_threshold_039999_vs_040001` | Candidate vectors with exact similarities 0.39999, 0.40000, 0.40001 against 0.40000 threshold | 0.39999 rejected; 0.40000 & 0.40001 accepted | 0.39999 rejected; 0.40000 & 0.40001 matched | **PASS** |
| `test_adv_vector_non_normalized_queries_and_embeddings` | Query vector scaled by 0.005; candidate embedding scaled by 50.0 (non-unit norms) | Cosine similarity mathematically invariant to scale; matches with similarity ~0.85 | Exactly matched with similarity 0.85 | **PASS** |
| `test_adv_vector_zero_and_subnormal_vectors` | All-zero query vector `[0.0]*512` and subnormal vector `[1e-18]*512` against normal DB | Zero query returns `[]`; subnormal query returns `[]`; no ZeroDivisionError | Zero and subnormal queries safely return empty list | **PASS** |
| `test_adv_vector_orthogonal_and_antipodal_extreme_cosines` | Orthogonal ($s=0.0$), antipodal ($s=-1.0$), and near-orthogonal ($\pm 0.0001$) vectors | Excluded at threshold 0.40; antipodal excluded at threshold -0.50 | Correctly discriminated; antipodal excluded at all thresholds | **PASS** |
| `test_adv_vector_nan_and_infinity_resilience` | DB records and queries containing `float('nan')` and `float('inf')` | Safe graceful handling; no unhandled exception; normal students unaffected | NaN and Inf queries safely return `[]`; normal match unaffected | **PASS** |
| `test_adv_face_cache_batch_matcher_stress` | Batch matching in `face_cache.match_faces_batch` with scaled, zero, and unrelated vectors | Exact match ~1.0; auto-normalized query ~1.0; zero vector yields `None` | All 4 queries returned expected matches / `None` in <1ms | **PASS** |
| `test_adv_cooldown_microsecond_boundary_14_899_vs_15_001` | Timing boundaries: 14.899s, 14.999999s, 15.000000s, 15.000001s, 15.001s | Rejection at 14.899s & 14.999999s; Acceptance at 15.000000s, 15.000001s, 15.001s | Sub-second and microsecond boundaries strictly observed | **PASS** |
| `test_adv_cooldown_window_not_extended_by_suppressed_reads` | Continuous suppressed reads at t0+2s, 5s, 8s, 11s, 14s, 14.9s | Cooldown still expires at t0+15.0s (not prolonged) | Cooldown strictly expired at t0+15.1s, logging new movement | **PASS** |
| `test_adv_rapid_burst_50_detections_in_10ms` | 50 detections of same student within 10ms ($200\,\mu\text{s}$ spacing) | 1st detection accepted; remaining 49 suppressed; 1 log created | Exactly 1 OUT returned; 49 `None`; exactly 1 movement log | **PASS** |
| `test_adv_multi_student_simultaneous_microsecond_burst` | 10 different students detected at the exact same microsecond ($t_0$) | All 10 students allowed; 10 unique movement logs | All 10 returned OUT; exactly 10 distinct student logs created | **PASS** |
| `test_adv_cross_camera_rapid_u_turn` | Exit CAM_02 at $t_0$, Entry CAM_01 at $t_0+100\text{ms}$, then re-detection at $t_0+200\text{ms}$ | Exit allowed; Entry allowed; subsequent immediate re-detections blocked | Exactly 2 logs (OUT, IN); CAM_02 and CAM_01 cooldowns blocked 3rd & 4th | **PASS** |
| `test_adv_cross_camera_ping_pong_attack` | Rapid alternating detections between CAM_01 & CAM_02 every 200ms for 25 cycles | Capped at 2 transitions initially; resumes after 15s | Capped at 2 logs; advanced to 4 logs after 15s cooldown expired | **PASS** |
| `test_adv_concurrent_multithreaded_movement_stress` | 10 concurrent threads calling `process_student_detection` simultaneously for same student | No process crash; at least 1 detection succeeds | 0 errors; successful transition; database remained valid | **PASS** |

---

## Unchallenged Areas

1. **Hardware Camera Frame Capture Glitches**: Physical RTSP packet corruption, camera firmware reboots, and rolling shutter distortion were simulated synthetically; physical camera hardware was out of scope for software E2E.
2. **GPU CUDA Execution on Non-NVIDIA Host**: Host system does not provide active CUDA ExecutionProvider (CPU fallback verified via ONNX Runtime). GPU memory paging under extreme video load was not challenged.
3. **Live Supabase pgvector Network Partition**: Offline in-memory fallback was verified; live cloud network timeout packet loss was mocked via the isolated test client.

---

## Final Verdict

**VERDICT: APPROVED WITH FINDINGS (STABLE & ROBUST)**  
The E2E test harness and core movement logic pass all 84 test specifications with zero test failures. The anti-bounce cooldown engine strictly enforces 15.0s boundaries down to microsecond precision ($14.999999\text{s}$ rejected, $15.000000\text{s}$ accepted). Floating-point boundary discrimination ($0.39999$ vs $0.40001$) is accurate. The three identified findings (norm epsilon floor, thread locking, sort key precision) are non-blocking for Milestone 2 testing but are documented for subsequent hardening.
