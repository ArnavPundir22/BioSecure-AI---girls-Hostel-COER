# Review & Adversarial Stress-Test Report: E2E Tier 3 & Tier 4 Suite

**Reviewer**: Reviewer 2 (E2E Test Suite - Tier 3 & Tier 4 Reviewer / Adversarial Critic)  
**Target Files**:
- `tests/e2e/test_tier3_combinations.py`
- `tests/e2e/test_tier4_scenarios.py`
- `TEST_INFRA.md`
- `TEST_READY.md`

**Verdict**: **REQUEST_CHANGES**

---

## 1. Executive Summary

| Scope | Metric / Requirement | Target / Claim | Actual Result | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Tier 3 Tests** | Cross-Feature Combinations | $\ge 8$ tests | **10 tests** | ✅ PASSED (10/10) |
| **Tier 4 Tests** | Real-World Operational Scenarios | $\ge 5$ tests | **5 tests** | ✅ PASSED (5/5) |
| **Full E2E Suite** | `.venv/bin/pytest tests/e2e -v` | 71 tests | **71 tests passed** (0 failed) | ✅ 100% PASS |
| **Full Repo Suite** | `.venv/bin/pytest tests -v` | 104 tests (claimed in `TEST_READY.md`) | **124 tests** (123 passed, 1 failed) | ❌ **FAIL** (Exit code 1) |
| **Documentation** | `TEST_READY.md` Total Counts | 104 tests total | Discrepancy: 124 collected | ❌ INACCURATE |

The Tier 3 and Tier 4 test suites are well-engineered, robustly conceived, deterministic, and rigorously validate multi-feature integration workflows and real-world operational scenarios. However, the overall project test run `.venv/bin/pytest tests -v` encounters **1 failure** (`tests/unit/test_m1_adversarial.py::TestSystemSettingsTampering::test_circular_reference_in_value_does_not_hang`), and `TEST_READY.md` contains an inaccurate accounting of the total test count and claims 100% pass rate for the full test suite when that command actually fails.

---

## 2. Test Execution Findings

### 2.1 E2E Test Suite (`.venv/bin/pytest tests/e2e -v`)
- **Collected**: 71 items
- **Passed**: 71
- **Failed**: 0
- **Duration**: ~61.7s
- **Tier 3 Breakdown**:
  - `test_t3_01_departure_return_lifecycle_with_dashboard_sync`: PASSED
  - `test_t3_02_entry_cooldown_curfew_immunity`: PASSED
  - `test_t3_03_exit_curfew_breach_alert_resolution_reentry`: PASSED
  - `test_t3_04_concurrent_dual_gate_simultaneous_detections`: PASSED
  - `test_t3_05_camera_cooldown_isolation_across_gates`: PASSED
  - `test_t3_06_low_similarity_match_rpc_rejection_pipeline`: PASSED
  - `test_t3_07_exit_immediately_preceding_curfew_cutoff`: PASSED
  - `test_t3_08_resolved_alert_subsequent_outing_alert_cycle`: PASSED
  - `test_t3_09_multi_face_batch_detection_exit_overdue_sync`: PASSED
  - `test_t3_10_schema_isolation_across_endpoints_and_engine`: PASSED
- **Tier 4 Breakdown**:
  - `test_t4_01_friday_evening_rush_and_curfew_breach`: PASSED
  - `test_t4_02_multi_student_overdue_batch_dispatch_and_rapid_resolution`: PASSED
  - `test_t4_03_morning_rush_gate_congestion_and_lingering`: PASSED
  - `test_t4_04_full_24hr_cycle_system_window_transitions`: PASSED
  - `test_t4_05_high_load_dual_gate_burst_with_concurrent_warden_polling`: PASSED

### 2.2 Full Test Suite (`.venv/bin/pytest tests -v`)
- **Collected**: 124 items (71 E2E + 28 `test_m1_schema_db.py` + 25 `test_m1_adversarial.py`)
- **Passed**: 123
- **Failed**: 1
- **Duration**: ~62.7s
- **Failure Details**:
  ```
  FAILED tests/unit/test_m1_adversarial.py::TestSystemSettingsTampering::test_circular_reference_in_value_does_not_hang
  AssertionError: True is not false
  ```

---

## 3. Findings & Defects

### [Critical] Finding 1: Project Test Suite Failure (`pytest tests -v`)
- **What**: `tests/unit/test_m1_adversarial.py::TestSystemSettingsTampering::test_circular_reference_in_value_does_not_hang` fails with `AssertionError: True is not false`.
- **Where**: `tests/unit/test_m1_adversarial.py:490`
- **Why**: The test expects `update_system_settings("circular_key", circular)` to return `False` when given a dictionary with a self-reference. However, `update_system_settings` in `src/utils/hostel_db.py` invokes `MockTableQuery.upsert()`, which uses Python's standard `copy.deepcopy(item)`. Python's `deepcopy` uses an internal memo table to handle circular references cleanly without raising `RecursionError`. As a result, the upsert succeeds and returns `True`, causing the test assertion `self.assertFalse(ok)` to fail.
- **Suggestion**: Either:
  1. In `src/utils/hostel_db.py:update_system_settings()`, validate JSON serializability (e.g., `json.dumps(value)`) before saving, which accurately reflects PostgreSQL's inability to store non-serializable circular structures; OR
  2. If Python object persistence is permitted in the mock, update the test assertion in `test_m1_adversarial.py`.

### [Major] Finding 2: Inaccurate Attestation & Test Accounting in `TEST_READY.md`
- **What**: `TEST_READY.md` claims:
  - Grand Total: 104 tests (71 E2E + 33 Unit)
  - Execution Status: "READY / 100% PASSING"
  - Command: `.venv/bin/pytest tests -v`
- **Where**: `TEST_READY.md:14-21` and `TEST_READY.md:64-66`
- **Why**:
  1. Pytest collects 124 tests (not 104) because `tests/unit/test_m1_adversarial.py` contains 25 tests that were omitted from `TEST_READY.md`'s summary table.
  2. Running `.venv/bin/pytest tests -v` exits with code 1 due to the unit test failure noted in Finding 1. Claiming "100% PASSING" for `.venv/bin/pytest tests -v` is an inaccurate attestation.
- **Suggestion**: Update `TEST_READY.md` to reflect the true test inventory (124 tests across unit and E2E tiers) once Finding 1 is resolved.

### [Minor / Quality] Finding 3: String Timestamp in Dashboard Resolve Endpoint
- **What**: In `src/blueprints/hostel.py:85`, the route `/hostel/api/resolve_alert` executes:
  ```python
  client.table("curfew_alerts").update({
      "status": "RESOLVED",
      "resolved_at": "now()",
      "notes": notes
  }).eq("id", alert_id).execute()
  ```
  While `hostel_db.resolve_curfew_alert` writes an ISO-8601 formatted timestamp (`datetime.now(timezone.utc).isoformat()`), the blueprint route bypasses `hostel_db` and hardcodes `"now()"`.
- **Where**: `src/blueprints/hostel.py:85`
- **Why**: In PostgreSQL, `"now()"` evaluates fine as SQL, but against in-memory mock clients or API consumers parsing ISO timestamps, it produces a literal string `"now()"` instead of an ISO datetime string.
- **Suggestion**: Use `hostel_db.resolve_curfew_alert(alert_id, notes=notes)` inside `src/blueprints/hostel.py` to maintain consistent timestamp formats and DRY principles.

---

## 4. Opaque-Box & Realism Assessment of Tier 3 & Tier 4

### 4.1 Opaque-Box Integrity
- **Contract Adherence**: Tier 3 and Tier 4 tests interact exclusively with public contracts:
  - REST endpoints: `/hostel/api/stats`, `/hostel/api/movement_logs`, `/hostel/api/overdue_alerts`, `/hostel/api/resolve_alert`
  - Ingestion state engine: `hostel_state.process_student_detection`
  - Curfew background engine: `curfew_service.check_curfew_violations`
  - DB client interface: `hostel_db.*`
- **Zero Internal State Inspection**: Tests verify observable side-effects (movement logs in database, counts returned by stats API, active alert lists).
- **Anti-Cheat Verification**:
  - No hardcoded test responses or canned assertions were detected in `hostel_state.py`, `curfew_service.py`, `hostel_db.py`, or `blueprints/hostel.py`.
  - Vectors are mathematically generated with Gram-Schmidt orthogonalization (`generate_calibrated_vector_pair`).
  - Cosine similarity calculations in `_compute_cosine_sim` compute real Euclidean dot-product math.

### 4.2 Time-Travel & Determinism
- Microsecond-accurate frozen clocking via `unittest.mock.patch` across `hostel_state.datetime`, `curfew_service.datetime`, `hostel_db.datetime`, and `hostel_db.date`.
- Tests cleanly transition through time intervals:
  - 20s delta exceeding 15s cooldown (`T3-01`)
  - 14.9s vs 15.0s vs 15.1s cooldown boundaries
  - 19:29:58 -> 19:30:00 curfew cutoff (`T3-07`)
  - Multi-phase full 24-hour cycle (`T4-04`: 14:00, 17:00, 19:29:59, 19:30:01, 01:00 AM, 06:15 AM)
- All time-traveling tests execute deterministically without race conditions or flaky timeouts.

### 4.3 Scenario Realism (Tier 4)
- **Scale**: Up to 20 concurrent students and 50 rapid multi-threaded detections.
- **Congestion & Tailgating**: `T4-03` simulates student lingering in front of gate camera for 14 seconds with interleaved passing students, verifying both cooldown suppression and pre-state debouncing.
- **Concurrency & Stress**: `T4-05` validates that 3 concurrent dashboard polling threads maintain atomic headcount consistency (`total_students == total_in + total_out`) during a 50-event burst across dual gates.

---

## 5. Adversarial Challenge & Stress-Test Matrix

| Challenge ID | Target Component | Attack Scenario / Assumption | Result / Observed Behavior | Severity |
| :--- | :--- | :--- | :--- | :---: |
| **ADV-01** | `curfew_service.py` | Overnight / Post-midnight curfew alert dating (01:00 AM on Date 2 creates alert under Date 2 instead of preceding day's session) | Scanner uses `now.date().isoformat()`, creating second alert if student stays out past midnight. Managed in tests via `len >= 1`. | Low / Design Quirk |
| **ADV-02** | `hostel_state.py` | Rapid cross-camera turnaround (Student exits at CAM_02, immediately re-enters CAM_01 within 2s) | Handled correctly: Cooldown is isolated per `(student_id, camera_id)`. Re-entry allowed. | Robust ✅ |
| **ADV-03** | `curfew_service.py` | Alert Idempotency under rapid sequential scan bursts (3 scans in 3 seconds at 19:30:00) | Handled correctly: `idx_girls_hostel_curfew_active_uniq` and duplicate check prevent duplicate alerts. | Robust ✅ |
| **ADV-04** | `hostel_db.py` | Deeply nested and circular references in system settings payload | Fails in `test_m1_adversarial.py` because `update_system_settings` does not validate JSON serializability before storage. | Medium (Finding 1) |
| **ADV-05** | `blueprints/hostel.py` | SQL injection attempt in `resolve_alert` notes and malformed payloads | Handled correctly: PostgREST parameter binding and input checks reject malformed payloads without crash. | Robust ✅ |

---

## 6. Recommendations

1. **Resolve Finding 1**: Fix `update_system_settings` or `test_circular_reference_in_value_does_not_hang` so that `.venv/bin/pytest tests -v` achieves 100% pass rate.
2. **Update `TEST_READY.md`**: Update total test numbers to 124 (71 E2E + 53 Unit) and ensure the attestation matches actual test command results.
3. **Refactor Blueprint Resolve**: Replace direct mock client update in `src/blueprints/hostel.py` with `hostel_db.resolve_curfew_alert()`.
