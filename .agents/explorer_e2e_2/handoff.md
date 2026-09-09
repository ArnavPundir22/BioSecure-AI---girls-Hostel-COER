# Handoff Report: E2E Test Architecture (R3 & R4 Focus)

**Agent:** Explorer 2 (E2E Test Architecture - R3 & R4)  
**Working Directory:** `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2`  
**Parent:** Sub-Orchestrator (E2E Testing Track, ID: `6b4995ac-f4d9-4ba4-ba90-04c764d29c0f`)  
**Date:** 2026-09-09  
**Target Specifications:** Analysis in `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2/analysis.md`

---

## 1. Observation

### 1.1 Codebase Implementation Observations

1. **Movement State Machine & Cooldown (`src/utils/hostel_state.py`)**:
   - Lines 16-19:
     ```python
     COOLDOWN_SECONDS: int = 15
     _cooldown_registry: Dict[str, Tuple[str, datetime]] = {}
     ```
   - Lines 28-34:
     ```python
     if student_id in _cooldown_registry:
         last_cam, last_time = _cooldown_registry[student_id]
         time_elapsed = (now - last_time).total_seconds()
         if last_cam == camera_id and time_elapsed < COOLDOWN_SECONDS:
             logger.debug(f"Cooldown active for student {student_id} on {camera_id} ({time_elapsed:.1f}s elapsed). Skipping.")
             return None
     ```
   - Lines 39-42:
     ```python
     if "ENTRY" in camera_id.upper() or camera_id == "CAM_01_ENTRY":
         target_direction = "IN"
     elif "EXIT" in camera_id.upper() or camera_id == "CAM_02_EXIT":
         target_direction = "OUT"
     ```
   - Lines 49-60:
     ```python
     success = hostel_db.update_student_movement_state(
         student_id=student_id,
         direction=target_direction,
         camera_id=camera_id
     )
     if success:
         _cooldown_registry[student_id] = (camera_id, now)
         return target_direction
     ```

2. **Curfew Schedule & Overdue Scanner (`src/services/curfew_service.py`)**:
   - Lines 20-21:
     ```python
     DEFAULT_START_TIME = dtime(17, 0, 0)  # 5:00 PM
     DEFAULT_CURFEW_END = dtime(19, 30, 0) # 7:30 PM
     ```
   - Lines 30-34:
     ```python
     now = datetime.now()
     current_time = now.time()
     if current_time >= DEFAULT_CURFEW_END:
     ```
   - Lines 52-68:
     ```python
     existing = client.table("curfew_alerts") \
         .select("id") \
         .eq("student_id", student_id) \
         .eq("curfew_date", today_str) \
         .eq("status", "OVERDUE_OUT") \
         .execute()

     if not existing.data:
         client.table("curfew_alerts").insert({
             "student_id": student_id,
             "curfew_date": today_str,
             "system_start_time": "17:00:00",
             "curfew_end_time": "19:30:00",
             "status": "OVERDUE_OUT"
         }).execute()
     ```
   - Lines 70-73:
     ```python
     logger.error(
         f"🚨 CURFEW BREACH ALERT: Student '{s.get('name')}' (Roll: {s.get('roll_number')}, "
         f"Room: {s.get('room_number')}) is OUT past 7:30 PM! Parent: {s.get('parent_contact')}"
     )
     ```

3. **Requirements & Contracts (`PROJECT.md` & `Rules.md`)**:
   - `PROJECT.md` (lines 94-99):
     > "If camera is ENTRY ('CAM_01_ENTRY') and student is 'OUT': updates status -> 'IN', logs direction='IN'.  
     > If camera is EXIT ('CAM_02_EXIT') and student is 'IN': updates status -> 'OUT', logs direction='OUT'.  
     > If detection occurs within 15 seconds of previous accepted event for same student & camera: ignore (cooldown active).  
     > If student is already 'IN' on ENTRY camera: ignore state change or debounce without error.  
     > If student is already 'OUT' on EXIT camera: ignore state change or debounce without error."
   - `Rules.md` (lines 13, 18, 22-24):
     > "Rule 01: Active Hours: Curfew enforcement scans remain active continuously from 19:30 until 06:00 the following morning.  
     > Rule 02.1: A student CANNOT transition to OUT if they are already recorded as OUT unless manually overridden by a hostel warden.  
     > Rule 03 Level 1: At 7:30 PM, any student whose current_status == 'OUT' is automatically flagged as OVERDUE_OUT.  
     > Rule 03 Level 3: If the student has not returned by 7:45 PM (15 minutes grace period), automated SMS/Email dispatching sends an urgent curfew alert to the registered parent contact (parent_contact)."

4. **Environment & Package Inventory**:
   - Inspection of `.venv/lib/python3.10/site-packages` confirms that `pytest` and `freezegun` are not installed in the current virtual environment. Standard library `unittest.mock` and `datetime` are available.

---

## 2. Logic Chain

1. **R3 Cooldown Boundary Logic**:
   - From Observation 1.1 (`time_elapsed < COOLDOWN_SECONDS` where `COOLDOWN_SECONDS = 15`), when $t_1 - t_0 = 14.9\text{s}$, $14.9 < 15$ evaluates to True, triggering `return None` and suppressing database writes.
   - When $t_1 - t_0 = 15.1\text{s}$, $15.1 < 15$ evaluates to False, allowing execution to proceed to database status updates and movement logging.
   - When $t_1 - t_0 = 15.000\text{s}$, $15.0 < 15$ evaluates to False, strictly confirming boundary acceptance.
   - Cross-camera evaluation: When a student exits at `CAM_02_EXIT` and then reaches `CAM_01_ENTRY` at $t_0 + 2.5\text{s}$, `last_cam == camera_id` is False. Thus, entry is not blocked by exit cooldown.

2. **R3 Debounce Logic & Anomaly**:
   - Observation 1.3 states that a student already `IN` on ENTRY camera or already `OUT` on EXIT camera must be debounced without error.
   - Observation 1.1 shows `process_student_detection` unconditionally calls `update_student_movement_state` without verifying if `current_status == target_direction`.
   - Logic deduction: The test suite must test both transitions (`IN` $\to$ `OUT` and `OUT` $\to$ `IN`) and debouncing of existing state (`IN` at ENTRY, `OUT` at EXIT) to prevent state pollution.

3. **R4 Curfew Boundary & Scanning Logic**:
   - From Observation 1.2 (`if current_time >= DEFAULT_CURFEW_END:` with `DEFAULT_CURFEW_END = 19:30:00`):
     - At $19:29:59$, `current_time < 19:30:00` $\implies$ scan exits immediately, zero alerts inserted.
     - At $19:30:00$, `19:30:00 >= 19:30:00` is True $\implies$ scan evaluates `current_status == 'OUT'` students, inserting alert with status `'OVERDUE_OUT'`.
     - At $19:30:01$, `19:30:01 >= 19:30:00` is True $\implies$ scan executes.
     - Before 17:00:00 (e.g. 15:00:00) and between 17:00:00 and 19:29:59 (e.g. 18:00:00), `current_time < 19:30:00` $\implies$ zero alerts.
   - Post-midnight rollover vulnerability: In Observation 1.2, `current_time` at 01:00 AM evaluates $01:00 \ge 19:30$ as False, failing Rule 01 (active until 06:00). Documented as an architectural finding and boundary test case.

4. **R4 Idempotency & Resolution Logic**:
   - From Observation 1.2, `existing` alert lookup checks `.eq("status", "OVERDUE_OUT")`.
   - Repeated scans on the same date find the existing alert and skip insertion (idempotent).
   - If warden marks the alert `RESOLVED`, the query `.eq("status", "OVERDUE_OUT")` returns empty, causing a subsequent scan to re-insert an alert. Test case `TEST-R4-T2-07` captures this critical edge case.

5. **Timing Control Logic**:
   - From Observation 1.4 (`freezegun` not in `.venv`), test suites must not fail due to missing external packages.
   - Standard library `unittest.mock.patch` targeting `src.utils.hostel_state.datetime` and `src.services.curfew_service.datetime` provides deterministic sub-second time travel without external dependencies.

---

## 3. Caveats

1. **Hardware & Real Video Feeds**: Tests validate the state engine and curfew scanner logic via direct invocation and mocked frame detections, not real RTSP video capture cards.
2. **External SMTP/SMS Service**: Actual email delivery to parent email addresses was not tested over external SMTP networks due to CODE_ONLY network restrictions; verification relies on logger capture and DB record persistence.
3. **Database Client Mode**: Tests are designed to run in two modes: in-memory mock mode (fast, hermetic) and live Supabase mode (`girls_hostel` schema with per-test transaction rollback). Live mode requires PostgreSQL credentials in `.env`.
4. **No Assumptions on Implementation Fixes**: The test suite designs define expected contracts from `PROJECT.md` and `Rules.md`. When current implementation differs (e.g. midnight rollover or re-alerting resolved alerts), test assertions will cleanly surface these as actionable defects.

---

## 4. Conclusion

1. **Opaque-Box Test Strategy Formulated**:
   - 29 detailed test case specifications created across R3 and R4:
     - **R3 Tier 1 (Core Features)**: 6 test cases (`TEST-R3-T1-01` to `TEST-R3-T1-06`).
     - **R3 Tier 2 (Boundaries & Corners)**: 8 test cases (`TEST-R3-T2-01` to `TEST-R3-T2-08`).
     - **R4 Tier 1 (Core Features)**: 6 test cases (`TEST-R4-T1-01` to `TEST-R4-T1-06`).
     - **R4 Tier 2 (Boundaries & Corners)**: 9 test cases (`TEST-R4-T2-01` to `TEST-R4-T2-09`).
2. **Key Boundaries Explicitly Covered**:
   - R3: $14.9\text{s}$ rejected, $15.0\text{s}$ boundary, $15.1\text{s}$ accepted, independent cross-camera streams, registry reset.
   - R4: $19:29:59$ not overdue, $19:30:00$ exact cutoff, $19:30:01$ overdue, $15:00:00$ (before system start), $18:00:00$ (permitted window), repeated scan idempotency, parent contact verification, midnight rollover.
3. **Timing Fixture Engineered**:
   - Designed a zero-dependency `FrozenClock` fixture using standard library `unittest.mock` to ensure immediate test execution compatibility in any environment.
4. **Implementation Risks Flagged**:
   - Documented 5 architectural anomalies (cooldown registry keying, debounce check, midnight rollover, re-alerting resolved students, timezone discrepancy) with concrete remediation recommendations in `analysis.md`.

---

## 5. Verification Method

### 5.1 Artifact Files to Inspect
- Detailed Test Specifications & Analysis:  
  `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2/analysis.md`
- Original Request & Task Record:  
  `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2/ORIGINAL_REQUEST.md`
- Heartbeat & Progress:  
  `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2/progress.md`

### 5.2 Test Execution Commands
When implementers create the test files based on this architecture:
```bash
# Run R3 movement state & cooldown tests
.venv/bin/python -m pytest tests/e2e/test_hostel_movement_r3.py -v

# Run R4 curfew schedule & alert scanner tests
.venv/bin/python -m pytest tests/e2e/test_hostel_curfew_r4.py -v

# Run combined suite with timing assertions
.venv/bin/python -m pytest tests/e2e/test_hostel_movement_r3.py tests/e2e/test_hostel_curfew_r4.py -v --tb=short
```

### 5.3 Invalidation Conditions
This test strategy is invalidated if:
1. Curfew window parameters are altered in `girls_hostel.system_settings` without updating default test parameters (e.g. cutoff changed from 19:30 to 20:00).
2. Anti-bounce cooldown window in `hostel_state.py` is modified from 15 seconds to a different value.
3. PostgreSQL schema name changes from `girls_hostel` to another namespace.
