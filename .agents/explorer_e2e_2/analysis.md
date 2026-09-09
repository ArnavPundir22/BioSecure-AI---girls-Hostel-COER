# Opaque-Box Test Architecture & Strategy: R3 (Movement State Machine) & R4 (Curfew Scanner)

**Author:** Explorer 2 (E2E Test Architecture)  
**Date:** 2026-09-09  
**Target Scope:** Requirements R3 (Movement State Machine & Cooldown Engine) and R4 (Curfew Schedule & Overdue Alert Scanner)  
**Location:** `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2/analysis.md`

---

## 1. Executive Summary

This document establishes the comprehensive opaque-box test strategy for **Requirement 3 (R3: Movement State Machine & Cooldown Engine)** and **Requirement 4 (R4: Curfew Schedule & Overdue Alert Scanner)** of the BioSecure AI - Girls Hostel Security System.

Opaque-box (black-box) testing verifies system compliance against requirements purely through defined interfaces, observable side-effects (database state in `girls_hostel.*`, API responses, return codes, generated alerts, log messages), and boundary stress-testing, without coupling test assertions to internal implementation variables.

### Key Investigation Highlights
1. **R3 Cooldown & State Invariants**:
   - Sub-second anti-bounce boundary: Detections at $t_0 + 14.9\text{s}$ must be suppressed; detections at $t_0 + 15.1\text{s}$ must be accepted.
   - Cross-camera decoupling: Detection at `CAM_02_EXIT` must not block legitimate entry at `CAM_01_ENTRY`.
   - Debouncing existing state: Student already `IN` detected at `CAM_01_ENTRY` or already `OUT` at `CAM_02_EXIT` must not cause corrupted state transitions or duplicate erroneous logs.
2. **R4 Curfew Window & Scanning Invariants**:
   - Sub-second curfew cutoff boundary: Scan at $19:29:59$ must NOT flag students as overdue; scan at $19:30:00$ and $19:30:01$ MUST flag students who are `OUT`.
   - Idempotency: Multiple scans after 19:30 (e.g. 19:31, 19:32, 19:35) must NOT generate duplicate active alerts for the same student on the same date.
   - Contact alerting: Parent contact (`parent_contact`) must be strictly extracted and dispatched in alert logs and UI payloads.
3. **Critical Code Anomalies Uncovered**:
   - **Cooldown Key Scope**: `src/utils/hostel_state.py` currently indexes `_cooldown_registry[student_id]`, meaning an exit detection immediately followed by entry detection overwrites the camera ID, breaking per-camera debounce independence.
   - **Missing Pre-State Debounce Guard**: `process_student_detection` lacks an explicit check for `current_status == target_direction`, potentially inserting duplicate movement logs when students re-trigger the same gate after 15 seconds.
   - **Midnight Rollover Vulnerability**: `curfew_service.py` evaluates `current_time >= DEFAULT_CURFEW_END` (19:30). If a scan occurs between 00:00 and 06:00 (active curfew according to `Rules.md`), `01:00 >= 19:30` evaluates to `False`, silently dropping overnight violations.
   - **Timezone Mismatch**: `hostel_state.py` uses `datetime.now(timezone.utc)` while `curfew_service.py` uses naive `datetime.now()`.

---

## 2. Requirement R3: Movement State Machine & Cooldown Engine

### 2.1 Interface & Behavioral Contracts

| Component | Target Contract (`PROJECT.md`, `Rules.md`, `PRD.md`) | Current Implementation (`src/utils/hostel_state.py`) |
|---|---|---|
| **Entry Point** | `process_student_detection(student_id: str, camera_id: str, student_info: dict) -> Optional[str]` | Implemented in `src/utils/hostel_state.py` |
| **CAM_01_ENTRY** | Direction `IN`. Updates `current_status = 'IN'`, writes `movement_logs(direction='IN')`. | `if "ENTRY" in camera_id.upper()` sets `target_direction = 'IN'`. Updates DB. |
| **CAM_02_EXIT** | Direction `OUT`. Updates `current_status = 'OUT'`, writes `movement_logs(direction='OUT')`. | `if "EXIT" in camera_id.upper()` sets `target_direction = 'OUT'`. Updates DB. |
| **Cooldown Window** | 15 seconds anti-bounce cooldown per student per camera stream. | 15 seconds (`COOLDOWN_SECONDS = 15`), checks `last_cam == camera_id and time_elapsed < 15`. |
| **Debounce Existing State** | If already `IN` on `CAM_01_ENTRY` or already `OUT` on `CAM_02_EXIT`, debounce/ignore state change without error (`Rules.md` Rule 02.1). | **Anomaly**: Currently calls `update_student_movement_state` regardless of `student_info.get("current_status")`. |
| **Unknown Camera ID** | Reject cross-directional or unknown cameras (`Rules.md` Rule 07.3). | Falls back to inverting current status (`target_direction = 'OUT' if current_status == 'IN' else 'IN'`). |

### 2.2 Cooldown Timing & Boundary Mathematics

Let $t_0$ be the timestamp of the first accepted movement event on camera $C$:
- **At $t \in [t_0, t_0 + 15.000\text{s})$**: `time_elapsed < 15.0`. The state engine must suppress the event:
  - Return: `None`
  - Database: Zero updates to `girls_hostel.student_profiles`, zero inserts into `girls_hostel.movement_logs`.
- **At $t = t_0 + 14.900\text{s}$**: Cooldown active ($14.9\text{s} < 15.0\text{s}$). Event MUST be rejected.
- **At $t = t_0 + 15.000\text{s}$**: Boundary condition. $15.0 < 15.0$ is False. Event is accepted.
- **At $t = t_0 + 15.100\text{s}$**: Cooldown expired ($15.1\text{s} \ge 15.0\text{s}$). Event MUST be accepted.
- **At $t = t_0 + \Delta t$ on Camera $C' \neq C$**:
  - Example: Student exits at `CAM_02_EXIT` at $t_0$, then reaches `CAM_01_ENTRY` at $t_0 + 2.0\text{s}$.
  - Cooldown on `CAM_01_ENTRY` has never fired (or expired). Event MUST be processed.

### 2.3 State Transition Matrix

| Initial Student State | Camera ID | Elapsed Since Last Same-Cam Event | Expected Return | Resulting Student State | Movement Log Inserted? |
|---|---|---|---|---|---|
| `IN` | `CAM_02_EXIT` | $N/A$ (First event) | `'OUT'` | `OUT` | Yes (`OUT`, `CAM_02_EXIT`) |
| `OUT` | `CAM_02_EXIT` | $3.5\text{s}$ | `None` | `OUT` | No (Cooldown active) |
| `OUT` | `CAM_02_EXIT` | $14.9\text{s}$ | `None` | `OUT` | No (Cooldown active) |
| `OUT` | `CAM_02_EXIT` | $15.1\text{s}$ | `None` or `'OUT'` (Debounced) | `OUT` | No / Debounced |
| `OUT` | `CAM_01_ENTRY` | $2.0\text{s}$ (after exit) | `'IN'` | `IN` | Yes (`IN`, `CAM_01_ENTRY`) |
| `IN` | `CAM_01_ENTRY` | $5.0\text{s}$ | `None` | `IN` | No (Cooldown active) |
| `IN` | `CAM_01_ENTRY` | $15.1\text{s}$ | `None` or `'IN'` (Debounced) | `IN` | No / Debounced |
| `IN` | `CAM_99_UNKNOWN` | $20.0\text{s}$ | Handled safely | `IN` (Uncorrupted) | No corrupt entries |

---

## 3. Requirement R4: Curfew Schedule & Overdue Alert Scanner

### 3.1 Interface & Behavioral Contracts

| Component | Target Contract (`PROJECT.md`, `Rules.md`, `PRD.md`) | Current Implementation (`src/services/curfew_service.py`) |
|---|---|---|
| **Entry Point** | `check_curfew_violations()` | Implemented in `src/services/curfew_service.py` |
| **System Window** | Start: `17:00:00` (5:00 PM), Curfew Cutoff: `19:30:00` (7:30 PM). Active until `06:00:00` next morning. | `DEFAULT_START_TIME = dtime(17, 0, 0)`, `DEFAULT_CURFEW_END = dtime(19, 30, 0)`. |
| **Scan Trigger Rule** | If `current_time >= 19:30:00`: evaluate all students where `current_status == 'OUT'`. | Evaluates `if current_time >= DEFAULT_CURFEW_END:`. Queries `hostel_db.fetch_all_hostel_students()`. |
| **Alert Table** | Insert into `girls_hostel.curfew_alerts` (`student_id`, `curfew_date`, `system_start_time`, `curfew_end_time`, `status='OVERDUE_OUT'`). | Inserts record with ISO date, `17:00:00`, `19:30:00`, `OVERDUE_OUT`. |
| **Idempotency** | Prevent duplicate active alerts for the same student on the same curfew date. | Queries `curfew_alerts` for `student_id`, `curfew_date`, and `status='OVERDUE_OUT'`. |
| **Parent Notification** | Log & broadcast overdue student details with `parent_contact`, `roll_number`, `room_number`. | Logs `🚨 CURFEW BREACH ALERT` with parent contact. |
| **Warden Dashboard API** | Reflect in `/hostel/api/overdue_alerts` and `/hostel/api/stats`. | Handled via `src/blueprints/hostel.py`. |

### 3.2 Curfew Timing Boundaries

```
Daytime (Normal)        Evening Permitted Outing        Curfew Cutoff        Overdue Active Enforcement
[06:00:00 ------------ 17:00:00 ------------------- 19:29:59] | [19:30:00 ---------------------- 23:59:59 -> 06:00:00]
     No alert                    No alert                 No alert   |               OVERDUE_OUT Alert Triggered
```

1. **Before System Start ($t < 17:00:00$, e.g. $15:00:00$)**:
   - Students outside hostel are engaged in regular daytime classes/activities.
   - Scanner must produce **zero** alerts.
2. **Evening Pass Window ($17:00:00 \le t < 19:30:00$, e.g. $18:15:00$)**:
   - Students are permitted outside the hostel during evening hours before curfew.
   - Scanner must produce **zero** alerts.
3. **Sub-second Cutoff Boundary**:
   - **$t = 19:29:59$**: Exactly 1 second before cutoff. `current_time < 19:30:00`. Status: **NOT OVERDUE**. Zero alerts.
   - **$t = 19:30:00$**: Exact cutoff time. `current_time >= 19:30:00`. Status: **OVERDUE**. Alert inserted.
   - **$t = 19:30:01$**: 1 second past cutoff. Status: **OVERDUE**. Alert inserted.
4. **Post-Midnight Rollover ($00:00:00 \le t < 06:00:00$, e.g. $01:15:00$)**:
   - Under `Rules.md` Rule 01, curfew remains active until 06:00 the following morning.
   - A student still OUT at 01:15 AM is critically overdue. The test suite must verify proper overnight evaluation.

---

## 4. Test Suite Architecture & Fixtures

### 4.1 Timing Control Recommendation

Testing sub-second boundaries (14.9s vs 15.1s, 19:29:59 vs 19:30:01) requires deterministic, microsecond-accurate time manipulation.

#### Option A: `unittest.mock.patch` on `datetime` (Recommended — Zero Dependency)
Because `requirements.txt` does not include `freezegun`, and external package installation may be restricted, we provide a pure Python standard library `frozen_time` context manager:

```python
import datetime
from unittest.mock import patch

class FrozenClock:
    def __init__(self, initial_datetime: datetime.datetime):
        self._current_datetime = initial_datetime

    def tick(self, seconds: float = 1.0):
        self._current_datetime += datetime.timedelta(seconds=seconds)
        return self._current_datetime

    def set(self, new_datetime: datetime.datetime):
        self._current_datetime = new_datetime

    def now(self, tz=None):
        if tz is not None and self._current_datetime.tzinfo is None:
            return self._current_datetime.replace(tzinfo=tz)
        return self._current_datetime
```

In `tests/conftest.py`, this mock is applied simultaneously to `src.utils.hostel_state.datetime` and `src.services.curfew_service.datetime`.

#### Option B: `freezegun.freeze_time` (When installed)
```python
@pytest.fixture
def freeze_clock():
    from freezegun import freeze_time
    def _freeze(time_str_or_dt):
        return freeze_time(time_str_or_dt, tick=True)
    return _freeze
```

### 4.2 Database Fixtures for Opaque-Box Isolation

To maintain 100% opaque-box integrity:
1. **`clean_hostel_db`**:
   - Sets up initial state in `girls_hostel.student_profiles` (e.g. 5 students `IN`, 2 students `OUT`).
   - Clears `girls_hostel.movement_logs` and `girls_hostel.curfew_alerts` before each test.
   - Clears `_cooldown_registry` in `hostel_state.py`.
2. **`mock_hostel_db_client`**:
   - For fast standalone execution without live Postgres, an in-memory dictionary-backed mock of `girls_hostel` schema emulating Supabase `.table().select().eq().execute()`.
3. **`assert_schema_isolation`**:
   - Asserts that zero queries or logs reference `public.*`.

---

## 5. Concrete Test Case Specifications

### 5.1 R3: Movement State Machine & Cooldown Engine

#### Tier 1: Core Feature Coverage (6 Test Cases)

```
Test ID: TEST-R3-T1-01
Name: test_r3_exit_gate_transitions_in_to_out
Requirement: R3 (CAM_02 Exit -> OUT)
Type: Tier 1 (Feature Coverage)
Precondition: Student S1 ('student-uuid-01') has current_status='IN' in girls_hostel.student_profiles.
Input Action:
    process_student_detection(
        student_id="student-uuid-01",
        camera_id="CAM_02_EXIT",
        student_info={"id": "student-uuid-01", "name": "Aanya Rao", "current_status": "IN"}
    )
Expected Result:
    - Return value is 'OUT'.
    - girls_hostel.student_profiles for S1 updated: current_status='OUT', last_movement_time is set.
    - girls_hostel.movement_logs contains new entry:
        student_id='student-uuid-01', direction='OUT', camera_id='CAM_02_EXIT'.
```

```
Test ID: TEST-R3-T1-02
Name: test_r3_entry_gate_transitions_out_to_in
Requirement: R3 (CAM_01 Entry -> IN)
Type: Tier 1 (Feature Coverage)
Precondition: Student S2 ('student-uuid-02') has current_status='OUT' in girls_hostel.student_profiles.
Input Action:
    process_student_detection(
        student_id="student-uuid-02",
        camera_id="CAM_01_ENTRY",
        student_info={"id": "student-uuid-02", "name": "Bhavna Patel", "current_status": "OUT"}
    )
Expected Result:
    - Return value is 'IN'.
    - girls_hostel.student_profiles for S2 updated: current_status='IN'.
    - girls_hostel.movement_logs contains new entry:
        student_id='student-uuid-02', direction='IN', camera_id='CAM_01_ENTRY'.
```

```
Test ID: TEST-R3-T1-03
Name: test_r3_cooldown_suppresses_duplicate_lingering_face
Requirement: R3 (15s Anti-bounce Cooldown)
Type: Tier 1 (Feature Coverage)
Precondition: Student S1 is detected on CAM_02_EXIT at t0 = 2026-09-09 17:15:00. Accepted -> 'OUT'.
Input Action:
    Advance clock to t0 + 4.0s (17:15:04).
    process_student_detection(
        student_id="student-uuid-01",
        camera_id="CAM_02_EXIT",
        student_info={"id": "student-uuid-01", "name": "Aanya Rao", "current_status": "OUT"}
    )
Expected Result:
    - Return value is None (suppressed).
    - Exactly 1 movement log remains in girls_hostel.movement_logs for S1.
    - Zero additional database updates executed.
```

```
Test ID: TEST-R3-T1-04
Name: test_r3_cooldown_expiry_allows_subsequent_event
Requirement: R3 (Cooldown Expiry & Subsequent Movement)
Type: Tier 1 (Feature Coverage)
Precondition: Student S1 exits via CAM_02_EXIT at t0 = 17:15:00. State -> 'OUT'.
Input Action:
    Advance clock to t0 + 25.0s (17:15:25, exceeding 15s cooldown).
    process_student_detection(
        student_id="student-uuid-01",
        camera_id="CAM_01_ENTRY",
        student_info={"id": "student-uuid-01", "name": "Aanya Rao", "current_status": "OUT"}
    )
Expected Result:
    - Return value is 'IN'.
    - Student status transitions to 'IN'.
    - Exactly 2 movement logs exist for S1 (first 'OUT' via CAM_02_EXIT, second 'IN' via CAM_01_ENTRY).
```

```
Test ID: TEST-R3-T1-05
Name: test_r3_multi_student_concurrent_cooldown_isolation
Requirement: R3 (Independent Cooldown per Student)
Type: Tier 1 (Feature Coverage)
Precondition: Student S1 and Student S2 arrive at CAM_02_EXIT simultaneously at t0 = 17:20:00.
Input Action:
    1. S1 detected at t0 -> accepted ('OUT').
    2. S2 detected at t0 -> accepted ('OUT').
    3. S1 lingers and is detected at t0 + 5.0s.
    4. S3 ('student-uuid-03', new arrival) detected at t0 + 5.0s.
Expected Result:
    - S1 at t0 + 5.0s is suppressed (returns None).
    - S3 at t0 + 5.0s is ACCEPTED (returns 'OUT').
    - S1's cooldown state does not block or delay S3.
```

```
Test ID: TEST-R3-T1-06
Name: test_r3_full_cycle_movement_roundtrip
Requirement: R3 (Complete Lifecycle State Tracking)
Type: Tier 1 (Feature Coverage)
Precondition: Student S1 starts 'IN'.
Input Action:
    1. t = 17:05:00: Detect at CAM_02_EXIT.
    2. t = 17:05:08: Detect at CAM_02_EXIT (lingering).
    3. t = 18:30:00: Detect at CAM_01_ENTRY (return).
Expected Result:
    - Step 1: Return 'OUT', student status becomes 'OUT'.
    - Step 2: Return None, suppressed.
    - Step 3: Return 'IN', student status becomes 'IN'.
    - Total movement logs created: exactly 2.
```

---

#### Tier 2: Boundary & Corner Cases (8 Test Cases)

```
Test ID: TEST-R3-T2-01
Name: test_r3_cooldown_boundary_14_9s_rejected
Requirement: R3 Boundary (14.9s Rejected)
Type: Tier 2 (Boundary Case)
Precondition: S1 detected at CAM_02_EXIT at t0 = 17:00:00.000. Accepted -> 'OUT'.
Input Action:
    Set clock to exactly t0 + 14.900s (17:00:14.900).
    process_student_detection("student-uuid-01", "CAM_02_EXIT", student_info)
Expected Result:
    - Return value: None.
    - Cooldown remains active (14.9s < 15.0s).
    - No movement log written. DB status remains unchanged.
```

```
Test ID: TEST-R3-T2-02
Name: test_r3_cooldown_boundary_15_1s_accepted
Requirement: R3 Boundary (15.1s Accepted)
Type: Tier 2 (Boundary Case)
Precondition: S1 detected at CAM_02_EXIT at t0 = 17:00:00.000. Accepted -> 'OUT'.
Input Action:
    Set clock to exactly t0 + 15.100s (17:00:15.100).
    process_student_detection("student-uuid-01", "CAM_01_ENTRY", {"id": "student-uuid-01", "current_status": "OUT"})
Expected Result:
    - Return value: 'IN'.
    - Cooldown expired (15.1s >= 15.0s).
    - Status updated to 'IN', movement log created.
```

```
Test ID: TEST-R3-T2-03
Name: test_r3_cooldown_boundary_exact_15_0s
Requirement: R3 Boundary (15.000s Exact Threshold)
Type: Tier 2 (Boundary Case)
Precondition: S1 detected at CAM_02_EXIT at t0 = 17:00:00.000.
Input Action:
    Set clock to exactly t0 + 15.000s.
    process_student_detection("student-uuid-01", "CAM_01_ENTRY", {"id": "student-uuid-01", "current_status": "OUT"})
Expected Result:
    - Evaluates: time_elapsed < 15.0 is FALSE (15.0 < 15.0 is False).
    - Event is ACCEPTED. Return 'IN'.
```

```
Test ID: TEST-R3-T2-04
Name: test_r3_different_cameras_independent_cooldown
Requirement: R3 Boundary (Per-Camera Stream Isolation)
Type: Tier 2 (Boundary Case)
Precondition: Student S1 detected at CAM_02_EXIT at t0 = 17:00:00.000. Status -> 'OUT'.
Input Action:
    Set clock to t0 + 2.5s (17:00:02.500).
    Student immediately turns back and enters CAM_01_ENTRY.
    process_student_detection("student-uuid-01", "CAM_01_ENTRY", {"id": "student-uuid-01", "current_status": "OUT"})
Expected Result:
    - CAM_01_ENTRY is NOT suppressed by CAM_02_EXIT cooldown.
    - Return value is 'IN'.
    - Student status transitions back to 'IN'.
```

```
Test ID: TEST-R3-T2-05
Name: test_r3_debouncing_already_in_on_entry_camera
Requirement: R3 Corner Case (Already IN Debouncing)
Type: Tier 2 (Corner Case)
Precondition: Student S1 current_status is 'IN'. Prior cooldown is expired.
Input Action:
    Student walks past CAM_01_ENTRY again (e.g. loitering inside gate).
    process_student_detection("student-uuid-01", "CAM_01_ENTRY", {"id": "student-uuid-01", "current_status": "IN"})
Expected Result:
    - System handles debouncing without crashing.
    - Current status remains 'IN'.
    - Does not record anomalous movement direction or throw unhandled exceptions.
```

```
Test ID: TEST-R3-T2-06
Name: test_r3_debouncing_already_out_on_exit_camera
Requirement: R3 Corner Case (Already OUT Debouncing / Rule 02.1)
Type: Tier 2 (Corner Case)
Precondition: Student S1 current_status is 'OUT'. Prior cooldown is expired.
Input Action:
    Student detected again on CAM_02_EXIT.
    process_student_detection("student-uuid-01", "CAM_02_EXIT", {"id": "student-uuid-01", "current_status": "OUT"})
Expected Result:
    - System enforces Rule 02.1: A student cannot transition to OUT if already OUT.
    - Status remains 'OUT'.
    - No contradictory state changes.
```

```
Test ID: TEST-R3-T2-07
Name: test_r3_unknown_camera_identifier_fallback
Requirement: R3 Corner Case (Robust Camera ID Handling)
Type: Tier 2 (Corner Case)
Precondition: Student S1 is 'IN'.
Input Action:
    process_student_detection("student-uuid-01", "INVALID_CAMERA_99", {"id": "student-uuid-01", "current_status": "IN"})
Expected Result:
    - System logs a warning and does not corrupt schema integrity.
    - Does not crash the ingestion worker thread.
```

```
Test ID: TEST-R3-T2-08
Name: test_r3_cooldown_registry_reset_behavior
Requirement: R3 Reset Logic (Worker Reboot / Registry Clear)
Type: Tier 2 (Corner Case)
Precondition: S1 detected on CAM_02_EXIT at t0. Cooldown active.
Input Action:
    Invoke registry reset / clear (_cooldown_registry.clear()).
    Set clock to t0 + 1.0s.
    Detect S1 on CAM_02_EXIT again.
Expected Result:
    - Cooldown state is cleared cleanly.
    - Subsequent detection is treated as a fresh detection cycle.
```

---

### 5.2 R4: Curfew Schedule & Overdue Alert Scanner

#### Tier 1: Core Feature Coverage (6 Test Cases)

```
Test ID: TEST-R4-T1-01
Name: test_r4_overdue_scan_flags_student_out_past_curfew
Requirement: R4 (Overdue Flagging at Cutoff)
Type: Tier 1 (Feature Coverage)
Precondition:
    - Clock set to 19:35:00 (past 19:30 curfew deadline).
    - Student S1 ('student-uuid-01') has current_status='OUT'.
    - Student S2 ('student-uuid-02') has current_status='IN'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Exactly 1 record created in girls_hostel.curfew_alerts.
    - Alert record contains:
        student_id='student-uuid-01', status='OVERDUE_OUT',
        curfew_date=today, system_start_time='17:00:00', curfew_end_time='19:30:00'.
    - Student S2 is NOT flagged.
```

```
Test ID: TEST-R4-T1-02
Name: test_r4_all_students_inside_zero_alerts
Requirement: R4 (Clean State when No Violations)
Type: Tier 1 (Feature Coverage)
Precondition:
    - Clock set to 19:40:00.
    - All registered students (e.g. 10 students) have current_status='IN'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Zero records inserted into girls_hostel.curfew_alerts.
    - Logs confirm: "All students are inside hostel. Zero curfew violations."
```

```
Test ID: TEST-R4-T1-03
Name: test_r4_batch_overdue_students_flagged
Requirement: R4 (Multi-Student Batch Overdue Detection)
Type: Tier 1 (Feature Coverage)
Precondition:
    - Clock set to 19:45:00.
    - 4 students are 'OUT' (S1, S3, S5, S7) and 6 students are 'IN'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Exactly 4 alert records created in girls_hostel.curfew_alerts.
    - Each record corresponds to S1, S3, S5, and S7 respectively.
```

```
Test ID: TEST-R4-T1-04
Name: test_r4_parent_contact_alert_logging
Requirement: R4 (Parent Contact Verification)
Type: Tier 1 (Feature Coverage)
Precondition:
    - Clock set to 19:31:00.
    - Student S1: name='Priya Sharma', roll_number='GH-101', room_number='A-204',
      parent_contact='+91-9876543210', current_status='OUT'.
Input Action:
    Execute check_curfew_violations() with logger capture enabled.
Expected Result:
    - Log output contains: "🚨 CURFEW BREACH ALERT"
    - Log explicitly includes "Priya Sharma", "GH-101", "A-204", and "+91-9876543210".
```

```
Test ID: TEST-R4-T1-05
Name: test_r4_curfew_alerts_api_visibility
Requirement: R4 (Warden API Reflection)
Type: Tier 1 (Feature Coverage)
Precondition:
    - check_curfew_violations() executed at 19:32:00, creating 2 OVERDUE_OUT alerts.
Input Action:
    Flask test client calls GET /hostel/api/overdue_alerts.
Expected Result:
    - Status code 200 OK.
    - JSON response contains 2 alert objects.
    - Each alert joins student_profiles: name, roll_number, room_number, parent_contact.
```

```
Test ID: TEST-R4-T1-06
Name: test_r4_warden_stats_overdue_count
Requirement: R4 (Dashboard Stats Accuracy)
Type: Tier 1 (Feature Coverage)
Precondition:
    - Database has 10 students total: 7 IN, 3 OUT.
    - Curfew scan executed at 19:35:00; 3 OVERDUE_OUT alerts active.
Input Action:
    Flask test client calls GET /hostel/api/stats.
Expected Result:
    - Status code 200 OK.
    - Response JSON:
        {"total_students": 10, "total_in": 7, "total_out": 3, "overdue_count": 3, "curfew_window": "17:00 - 19:30"}
```

---

#### Tier 2: Boundary & Corner Cases (9 Test Cases)

```
Test ID: TEST-R4-T2-01
Name: test_r4_boundary_19_29_59_not_overdue
Requirement: R4 Boundary (19:29:59 Not Overdue)
Type: Tier 2 (Boundary Case)
Precondition:
    - Clock set to 19:29:59 (1 second before curfew cutoff).
    - Student S1 is 'OUT'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - current_time < DEFAULT_CURFEW_END is TRUE.
    - Scanner terminates without evaluating student records.
    - Zero records inserted into girls_hostel.curfew_alerts.
```

```
Test ID: TEST-R4-T2-02
Name: test_r4_boundary_19_30_00_exact_cutoff_overdue
Requirement: R4 Boundary (19:30:00 Exact Cutoff Trigger)
Type: Tier 2 (Boundary Case)
Precondition:
    - Clock set to exactly 19:30:00.
    - Student S1 is 'OUT'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - current_time >= DEFAULT_CURFEW_END is TRUE (19:30:00 >= 19:30:00).
    - Scanner executes violation logic.
    - S1 is flagged as 'OVERDUE_OUT'.
```

```
Test ID: TEST-R4-T2-03
Name: test_r4_boundary_19_30_01_overdue
Requirement: R4 Boundary (19:30:01 1-Second Post-Cutoff Overdue)
Type: Tier 2 (Boundary Case)
Precondition:
    - Clock set to 19:30:01.
    - Student S1 is 'OUT'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Evaluates as overdue.
    - 1 alert record inserted with status='OVERDUE_OUT'.
```

```
Test ID: TEST-R4-T2-04
Name: test_r4_before_system_start_15_00_zero_alerts
Requirement: R4 Boundary (Before 17:00 System Start)
Type: Tier 2 (Boundary Case)
Precondition:
    - Clock set to 15:00:00 (mid-afternoon).
    - Student S1 is 'OUT'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Scanner does not trigger.
    - Zero alerts created.
```

```
Test ID: TEST-R4-T2-05
Name: test_r4_evening_permitted_window_18_00_zero_alerts
Requirement: R4 Boundary (Permitted Window 17:00 - 19:29:59)
Type: Tier 2 (Boundary Case)
Precondition:
    - Clock set to 18:00:00.
    - Student S1 is 'OUT' (legitimate evening outing).
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Zero alerts created.
```

```
Test ID: TEST-R4-T2-06
Name: test_r4_multiple_scans_idempotency
Requirement: R4 Corner Case (Repeated Scan Idempotency)
Type: Tier 2 (Corner Case)
Precondition:
    - Student S1 is 'OUT'.
Input Action:
    1. Set clock to 19:31:00. Execute check_curfew_violations().
    2. Set clock to 19:32:00. Execute check_curfew_violations().
    3. Set clock to 19:35:00. Execute check_curfew_violations().
Expected Result:
    - Exactly 1 record exists in girls_hostel.curfew_alerts for S1 on today's date.
    - Duplicate scans detect existing alert and skip insertion.
```

```
Test ID: TEST-R4-T2-07
Name: test_r4_alert_resolution_and_subsequent_scan
Requirement: R4 Corner Case (Interaction with Resolved Alert)
Type: Tier 2 (Corner Case)
Precondition:
    - Alert created for S1 at 19:31:00.
    - Warden marks alert RESOLVED via POST /hostel/api/resolve_alert.
    - Student S1 remains 'OUT'.
Input Action:
    Set clock to 19:40:00. Execute check_curfew_violations().
Expected Result:
    - System respects warden's resolution. Does not re-insert duplicate alert for the same day.
```

```
Test ID: TEST-R4-T2-08
Name: test_r4_midnight_rollover_active_window
Requirement: R4 Boundary (Post-Midnight Scanning: 00:00 - 06:00)
Type: Tier 2 (Boundary Case)
Precondition:
    - Student S1 remained 'OUT' all evening.
    - Clock set to 01:15:00 the following morning.
Input Action:
    Execute curfew check under active curfew policy (Rules.md: 19:30 to 06:00).
Expected Result:
    - System correctly identifies student as still overdue or maintains active breach state.
    - Discloses architectural anomaly if naive time comparison fails.
```

```
Test ID: TEST-R4-T2-09
Name: test_r4_missing_or_malformed_parent_contact
Requirement: R4 Corner Case (Malformed Contact Field)
Type: Tier 2 (Corner Case)
Precondition:
    - Student S1 profile has parent_contact=None or empty string "".
    - Clock set to 19:35:00. Student is 'OUT'.
Input Action:
    Execute check_curfew_violations().
Expected Result:
    - Scanner inserts curfew alert into DB without throwing an unhandled exception.
    - Logger logs alert with "N/A" or graceful placeholder for parent contact.
```

---

## 6. Architectural Anomalies & Recommendations for Implementers

| # | Anomaly / Risk | Affected File & Lines | Severity | Recommended Fix |
|---|---|---|---|---|
| 1 | **Cooldown Registry Key Scope** | `src/utils/hostel_state.py:19,30,57` | High | Currently `_cooldown_registry[student_id] = (camera_id, now)`. Keys should be `(student_id, camera_id)` so CAM_01 and CAM_02 cooldowns are decoupled and do not overwrite each other. |
| 2 | **Missing Pre-State Debounce Check** | `src/utils/hostel_state.py:48-54` | Medium | If `student_info.get("current_status") == target_direction`, `process_student_detection` should debounce without inserting duplicate movement logs. |
| 3 | **Midnight Rollover Bug** | `src/services/curfew_service.py:34` | High | `current_time >= DEFAULT_CURFEW_END` fails past midnight (e.g. 01:00 AM < 19:30). Curfew window logic should be: `current_time >= 19:30 or current_time < 06:00`. |
| 4 | **Re-alerting Resolved Students** | `src/services/curfew_service.py:53-58` | Medium | Query filters `.eq("status", "OVERDUE_OUT")`. If warden marks alert `RESOLVED`, next scan sees no `OVERDUE_OUT` and re-inserts a new alert! Query should check if ANY alert exists for student today. |
| 5 | **Timezone Inconsistency** | `hostel_state.py` vs `curfew_service.py` | Medium | `hostel_state` uses `datetime.now(timezone.utc)` while `curfew_service` uses naive `datetime.now()`. Standardize to UTC or explicit timezone throughout. |

---

## 7. Verification Method

To verify these test specifications independently:
1. Review `tests/e2e/test_hostel_movement_r3.py` against Section 5.1 test designs.
2. Review `tests/e2e/test_hostel_curfew_r4.py` against Section 5.2 test designs.
3. Verify deterministic timing control using the frozen clock fixture in Section 4.1.
4. Execute test suite command:
   ```bash
   .venv/bin/python -m pytest tests/e2e/test_hostel_movement_r3.py tests/e2e/test_hostel_curfew_r4.py -v
   ```
