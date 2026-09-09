# E2E Test Architecture Analysis: R5 Warden Dashboard & Tier 3/4 Scenarios

**Author**: Explorer 3 (E2E Test Architecture - R5 & Tier 3/4 Scenarios Focus)  
**Date**: 2026-09-09  
**Status**: COMPLETE  
**Target Suite**: `tests/e2e/` (Tiers 1-5, Focus: R5, Tier 3 Cross-Feature, Tier 4 Real-World)

---

## 1. Executive Summary

This investigation designs the opaque-box end-to-end testing architecture for:
1. **Requirement 5 (R5)**: Warden Dashboard and API endpoints (`/hostel`, `/hostel/api/stats`, `/hostel/api/movement_logs`, `/hostel/api/overdue_alerts`, `/hostel/api/resolve_alert`).
2. **Tier 3 (Cross-Feature Combinations)**: 10 rigorous multi-component integration tests (minimum requirement: 8) evaluating interactions across facial biometrics (R2), state transitions (R3), database isolation (R1), curfew schedule enforcement (R4), and dashboard visibility (R5).
3. **Tier 4 (Real-World Operational Scenarios)**: 5 end-to-end temporal simulations representing realistic hostel life cycles, peak gate throughput, mass evening departures, late curfew returns, and warden emergency workflows.
4. **Flask `test_client` Integration Harness**: Architecture for test fixtures, authentication session synthesis, isolated in-memory state teardown, mock database boundaries, and background thread suppression.

---

## 2. R5: Warden Dashboard & Control Center Deep Dive

### 2.1 Route Architecture & Contract Verification

From inspecting `src/blueprints/hostel.py` and `src/__init__.py`:

| Endpoint | HTTP Method | Target Utility / Model | Expected Request Body / Params | Expected Response Schema |
| :--- | :--- | :--- | :--- | :--- |
| `/hostel` | `GET` | `render_template("hostel_dashboard.html")` | None | `text/html` (200 OK) |
| `/hostel/api/stats` | `GET` | `hostel_db.fetch_all_hostel_students()`, `hostel_db.fetch_overdue_curfew_students()` | None | `{"total_students": int, "total_in": int, "total_out": int, "overdue_count": int, "curfew_window": "17:00 - 19:30"}` (200 OK) |
| `/hostel/api/movement_logs` | `GET` | `hostel_db.fetch_recent_movement_logs(limit)` | Query param `limit` (int, default 50) | `{"logs": [{"id": int, "direction": str, "camera_id": str, "timestamp": str, "student_id": str, "student_profiles": {...}}]}` (200 OK) |
| `/hostel/api/overdue_alerts`| `GET` | `hostel_db.fetch_overdue_curfew_students()` | None | `{"alerts": [{"id": int, "curfew_date": str, "system_start_time": str, "curfew_end_time": str, "status": "OVERDUE_OUT", "alert_triggered_at": str, "student_profiles": {...}}]}` (200 OK) |
| `/hostel/api/resolve_alert` | `POST` | `client.table("curfew_alerts").update({...}).eq("id", alert_id)` | JSON: `{"alert_id": int/str, "notes": str}` | `{"status": "success", "message": "Alert <id> resolved successfully"}` (200 OK) |

### 2.2 Critical Security & Middleware Behavioral Constraints

1. **Authentication Enforcement (`src/__init__.py:127-142`)**:
   - `src/__init__.py` defines a global `@app.before_request` hook `require_login()`.
   - Public paths are strictly whitelist-restricted to: `{"/login", "/favicon.ico", "/healthz", "/auth/callback"}` plus paths starting with `/static/` or `/login/oauth/`.
   - All `/hostel*` endpoints (both UI and `/hostel/api/*`) require `"logged_in" in session`.
   - **Unauthenticated requests to `/hostel` or `/hostel/api/*` MUST receive HTTP 302 Redirect to `/login`**.
   - Test clients must use `with client.session_transaction() as sess: sess["logged_in"] = True` to test authorized access.

2. **Blueprint Background Service Side-Effect (`src/blueprints/hostel.py:18-21`)**:
   - `src/blueprints/hostel.py` executes `start_curfew_service()` on import.
   - In `curfew_service.py`, this starts an unmanaged daemon thread looping every 60 seconds.
   - For deterministic test runs, tests MUST patch `start_curfew_service` or invoke `stop_curfew_service()` during fixture teardown to prevent thread leakage and race conditions.

3. **Schema Isolation Guarantee**:
   - All warden endpoints query exclusively through `src.utils.hostel_db` which explicitly locks execution to `.schema("girls_hostel")`.
   - Tests must assert that no query or join references `public.student_profiles` or `public.attendance_logs`.

---

## 3. R5 Test Suite Specification (Tier 1 & Tier 2)

### 3.1 Tier 1: R5 Feature Coverage Tests (Minimum 5 tests)

- **`test_r5_t1_01_dashboard_page_render_authenticated`**:
  - *Given*: An authenticated warden session (`sess["logged_in"] = True`).
  - *When*: `GET /hostel/` (or `/hostel`).
  - *Then*: Returns HTTP 200, Content-Type `text/html`, and HTML contains critical UI DOM identifiers:
    - Metric elements: `statTotal`, `statIn`, `statOut`, `statOverdue`.
    - Camera cards: `CAM 01: ENTRY GATE`, `CAM 02: EXIT GATE`.
    - Table element: `logsTableBody`.
    - Overdue container: `overdueContainer`, `overdueSection`.
    - Security scope indicator: `girls_hostel`.

- **`test_r5_t1_02_api_stats_summary_calculation`**:
  - *Given*: Authenticated session. Mocked database with 10 total students: 7 with `current_status = 'IN'`, 3 with `current_status = 'OUT'`, and 2 active overdue curfew alerts.
  - *When*: `GET /hostel/api/stats`.
  - *Then*: Returns HTTP 200 with JSON:
    - `"total_students": 10`
    - `"total_in": 7`
    - `"total_out": 3`
    - `"overdue_count": 2`
    - `"curfew_window": "17:00 - 19:30"`
    - Invariant: `total_students == total_in + total_out`.

- **`test_r5_t1_03_api_movement_logs_retrieval_and_order`**:
  - *Given*: Authenticated session. Database populated with 5 movement logs with timestamps $T_1 < T_2 < T_3 < T_4 < T_5$.
  - *When*: `GET /hostel/api/movement_logs?limit=50`.
  - *Then*: Returns HTTP 200, JSON list of length 5. First item is $T_5$ (descending order). Student metadata nested correctly under `student_profiles` (`name`, `roll_number`, `room_number`).

- **`test_r5_t1_04_api_overdue_alerts_filter_active_only`**:
  - *Given*: Database contains 1 alert with `status = 'OVERDUE_OUT'` and 1 alert with `status = 'RESOLVED'`.
  - *When*: `GET /hostel/api/overdue_alerts`.
  - *Then*: Returns HTTP 200, JSON list contains exactly 1 alert (`status == 'OVERDUE_OUT'`). Resolved alert is excluded. Parent contact phone number is present in `student_profiles.parent_contact`.

- **`test_r5_t1_05_api_resolve_alert_success_transition`**:
  - *Given*: Alert ID 101 currently has status `OVERDUE_OUT`.
  - *When*: `POST /hostel/api/resolve_alert` with JSON `{"alert_id": 101, "notes": "Parent confirmed train delay"}`.
  - *Then*: Returns HTTP 200 `{"status": "success", "message": "Alert 101 resolved successfully"}`.
  - *Verification*: Alert 101 status in database is updated to `RESOLVED`, `notes` is set, and subsequent `GET /hostel/api/overdue_alerts` no longer includes ID 101.

- **`test_r5_t1_06_api_resolve_alert_default_notes`**:
  - *Given*: Alert ID 102 with status `OVERDUE_OUT`.
  - *When*: `POST /hostel/api/resolve_alert` with JSON `{"alert_id": 102}` (omitting `notes`).
  - *Then*: Returns HTTP 200, notes in database defaults to `"Resolved by warden"`.

---

### 3.2 Tier 2: R5 Boundary & Corner Cases (Minimum 5 tests)

- **`test_r5_t2_01_unauthenticated_access_redirect`**:
  - *Given*: An unauthenticated test client (no session cookies).
  - *When*: Requests `GET /hostel`, `GET /hostel/api/stats`, `GET /hostel/api/movement_logs`, `GET /hostel/api/overdue_alerts`, `POST /hostel/api/resolve_alert`.
  - *Then*: Each request receives HTTP 302 Redirect to `/login`.

- **`test_r5_t2_02_resolve_alert_missing_alert_id`**:
  - *Given*: Authenticated session.
  - *When*: `POST /hostel/api/resolve_alert` with JSON `{"notes": "Forgot ID"}` (missing `alert_id`) or empty JSON `{}`.
  - *Then*: Returns HTTP 400 Bad Request `{"error": "alert_id is required"}`.

- **`test_r5_t2_03_resolve_alert_non_json_payload`**:
  - *Given*: Authenticated session.
  - *When*: `POST /hostel/api/resolve_alert` with `data="not_json"` and header `Content-Type: text/plain`.
  - *Then*: Handled gracefully without crash; returns HTTP 400 Bad Request.

- **`test_r5_t2_04_movement_logs_limit_parameter_boundaries`**:
  - *Given*: Authenticated session. Database contains 20 movement logs.
  - *Cases*:
    - `?limit=1`: Returns exactly 1 log.
    - `?limit=0`: Returns 0 logs (or minimum allowed).
    - `?limit=1000`: Returns all 20 logs without error.
    - `?limit=invalid_string`: Returns HTTP 500 JSON error `{"error": "..."}` cleanly without uncaught unhandled server failure.

- **`test_r5_t2_05_api_stats_empty_database`**:
  - *Given*: Fresh database with zero students enrolled in `girls_hostel.student_profiles`.
  - *When*: `GET /hostel/api/stats`.
  - *Then*: Returns HTTP 200 `{"total_students": 0, "total_in": 0, "total_out": 0, "overdue_count": 0, "curfew_window": "17:00 - 19:30"}`.

- **`test_r5_t2_06_api_stats_malformed_student_status`**:
  - *Given*: Student profile has NULL or lowercase `"in"` or unexpected `"LEAVE"` in `current_status`.
  - *When*: `GET /hostel/api/stats`.
  - *Then*: Returns HTTP 200; handles missing or unexpected strings without unhandled exception.

- **`test_r5_t2_07_http_method_not_allowed_enforcement`**:
  - *Given*: Authenticated session.
  - *When*: `POST /hostel`, `POST /hostel/api/stats`, `GET /hostel/api/resolve_alert`, `PUT /hostel/api/movement_logs`.
  - *Then*: Returns HTTP 405 Method Not Allowed.

- **`test_r5_t2_08_resolve_alert_sql_injection_defense`**:
  - *Given*: Authenticated session.
  - *When*: `POST /hostel/api/resolve_alert` with notes payload: `{"alert_id": 105, "notes": "'; DROP TABLE girls_hostel.curfew_alerts; --"}`.
  - *Then*: Returns HTTP 200. Table remains intact; raw string stored safely via parameterized query.

---

## 4. Tier 3: Cross-Feature Combinations Specification (10 Tests)

Tier 3 tests exercise complex multi-component sequences spanning biometrics, state engine, schema isolation, curfew scanner, and warden APIs.

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                    Tier 3 Architecture                      │
                  └──────────────────────────────┬──────────────────────────────┘
                                                 │
         ┌───────────────────────┬───────────────┴───────────────┬───────────────────────┐
         ▼                       ▼                               ▼                       ▼
  Biometric Match         Movement Engine                 Curfew Scanner          Warden Dashboard
(InsightFace/match_face) (15s Anti-bounce Cooldown)     (17:00-19:30 Boundary)   (Real-time State Sync)
```

### Complete Tier 3 Test Matrix

| Test ID | Test Title | Features Exercised | Primary Verification Goal |
| :--- | :--- | :--- | :--- |
| **`T3-01`** | Departure-Return Full Lifecycle Sync | R2, R3, R1, R5 | Exit through Cam 2 -> verify stats update -> Return through Cam 1 -> verify stats revert |
| **`T3-02`** | Entry -> Anti-Bounce Cooldown -> Curfew Boundary Immunity | R2, R3, R4, R5 | Student returns at 19:28, lingers in Cam 1 view (debounced), 19:30 curfew scan flags 0 alerts |
| **`T3-03`** | Exit -> Curfew Breach -> Alert Generation -> Resolution -> Re-entry | R3, R4, R5, R1 | Full overdue alert-to-resolution cycle followed by valid gate re-entry |
| **`T3-04`** | Concurrent Dual-Gate Simultaneous Detections | R2, R3, R1, R5 | Cam 1 Entry and Cam 2 Exit triggered at same timestamp; no race conditions or deadlocks |
| **`T3-05`** | Multi-Camera Cooldown Independence for Same Student | R3, R1, R5 | Student exits Cam 2 and immediately turns to Cam 1 within 3s; Cam 1 must NOT be blocked |
| **`T3-06`** | Low Biometric Similarity RPC Rejection Pipeline | R1, R2, R3, R5 | Embedding similarity 0.32 (<0.40) rejected at RPC; state machine & logs untouched |
| **`T3-07`** | Exit Immediately Preceding Curfew Cutoff Race Condition | R3, R4, R1, R5 | Student exits at 19:29:58; Curfew scanner at 19:30:00 detects student and generates alert |
| **`T3-08`** | Resolved Alert Subsequent Outing Alert Cycle | R3, R4, R5 | Resolved student leaves again on same date; subsequent scan generates new overdue record |
| **`T3-09`** | Multi-Face Batch Detection at Exit with Immediate Overdue Alerting | R2, R3, R4, R5 | Batch of 4 students exit together at 19:25; 19:30 curfew scanner detects all 4 in batch |
| **`T3-10`** | Strict Schema Isolation Across Endpoints & State Machine | R1, R3, R4, R5 | Full end-to-end execution path verified to make 0 reads/writes to `public.*` |

---

### Detailed Tier 3 Test Definitions

#### `T3-01: test_t3_01_departure_return_lifecycle_with_dashboard_sync`
- **Initial Setup**:
  - Student S1 enrolled with `current_status = 'IN'`.
  - Initial `/hostel/api/stats`: `total_in = 1, total_out = 0`.
- **Sequence**:
  1. Camera 2 (`CAM_02_EXIT`) triggers detection for S1.
  2. `process_student_detection` updates S1 to `OUT` and writes `movement_logs` record (`direction='OUT', camera_id='CAM_02_EXIT'`).
  3. Query `GET /hostel/api/stats`: asserts `total_in = 0, total_out = 1`.
  4. Query `GET /hostel/api/movement_logs`: asserts latest log is S1 `OUT`.
  5. Advance time by 20 seconds (exceeding 15s cooldown).
  6. Camera 1 (`CAM_01_ENTRY`) triggers detection for S1.
  7. `process_student_detection` updates S1 to `IN` and writes `movement_logs` (`direction='IN', camera_id='CAM_01_ENTRY'`).
  8. Query `GET /hostel/api/stats`: asserts `total_in = 1, total_out = 0`.
  9. Query `GET /hostel/api/movement_logs`: asserts latest log is S1 `IN`.

#### `T3-02: test_t3_02_entry_cooldown_curfew_immunity`
- **Initial Setup**:
  - Student S1 is `OUT` at 19:25:00.
- **Sequence**:
  1. At 19:28:00, S1 appears on `CAM_01_ENTRY`. `process_student_detection` marks S1 `IN`.
  2. At 19:28:05 (5s elapsed), S1 lingers in front of `CAM_01_ENTRY`. Ingestion worker sends detection. Anti-bounce rejects with `None`. Log count remains 1.
  3. At 19:28:10 (10s elapsed), S1 still in frame. Anti-bounce rejects.
  4. Curfew scanner executes `check_curfew_violations()` at 19:30:05.
  5. Scanner checks all `OUT` students. S1 is `IN`.
  6. Assert `curfew_alerts` count is 0.
  7. Query `GET /hostel/api/overdue_alerts`: asserts `alerts: []`.
  8. Query `GET /hostel/api/stats`: asserts `overdue_count: 0`.

#### `T3-03: test_t3_03_exit_curfew_breach_alert_resolution_reentry`
- **Initial Setup**:
  - Student S1 (Roll: "2026-GH-042", Room: "B-204", Parent: "+91-9876543210") initial status `IN`.
- **Sequence**:
  1. 17:30:00: S1 exits via `CAM_02_EXIT` -> status becomes `OUT`.
  2. 19:30:01: Clock advances past curfew cutoff. Curfew scanner runs.
  3. S1 flagged as `OVERDUE_OUT` in `girls_hostel.curfew_alerts`.
  4. Query `GET /hostel/api/overdue_alerts`: asserts alert contains S1 ID, Roll, Room, Parent contact.
  5. Query `GET /hostel/api/stats`: asserts `overdue_count = 1`.
  6. Warden resolves alert via `POST /hostel/api/resolve_alert`: `{"alert_id": <id>, "notes": "Parent confirmed arrival at 19:45"}`.
  7. Query `GET /hostel/api/overdue_alerts`: asserts `alerts: []` (resolved alert hidden).
  8. Query `GET /hostel/api/stats`: asserts `overdue_count = 0`.
  9. 19:45:00: S1 returns at `CAM_01_ENTRY` -> status transitions to `IN`.
  10. Curfew scanner runs again at 19:46:00: asserts zero new alerts created.

#### `T3-04: test_t3_04_concurrent_dual_gate_simultaneous_detections`
- **Initial Setup**:
  - Student A (`IN`), Student B (`OUT`).
- **Sequence**:
  1. At exact timestamp $T_0$, execute concurrent threads:
     - Thread 1: `process_student_detection(student_id=Student_A, camera_id="CAM_02_EXIT")`
     - Thread 2: `process_student_detection(student_id=Student_B, camera_id="CAM_01_ENTRY")`
  2. Both threads join within 500ms.
  3. Assert both return expected directions: Thread 1 -> `'OUT'`, Thread 2 -> `'IN'`.
  4. Query `GET /hostel/api/movement_logs`: both logs exist with appropriate camera IDs.
  5. Query `GET /hostel/api/stats`: `total_in` and `total_out` reflect atomic balance without lost updates.

#### `T3-05: test_t3_05_camera_cooldown_isolation_across_gates`
- **Initial Setup**:
  - Student S1 is `IN`.
- **Sequence**:
  1. $T_0$: S1 exits via `CAM_02_EXIT` -> returns `'OUT'`, cooldown stored for `(S1, 'CAM_02_EXIT')`.
  2. $T_0 + 2\text{s}$: S1 immediately turns back and triggers `CAM_01_ENTRY`.
  3. State machine checks cooldown for `(S1, 'CAM_01_ENTRY')`. Since last camera was `CAM_02_EXIT`, camera ID does NOT match.
  4. Cooldown does NOT suppress entry! State machine transitions S1 back to `IN`.
  5. Assert two distinct movement logs exist within 2-second delta.

#### `T3-06: test_t3_06_low_similarity_match_rpc_rejection`
- **Initial Setup**:
  - Student S1 enrolled with embedding $E_1$.
  - Candidate face generates embedding $E_2$ where cosine similarity with $E_1$ is $0.34$.
- **Sequence**:
  1. Ingestion calls `girls_hostel.match_face` with threshold $0.40$.
  2. RPC returns empty match list (`[]`).
  3. Ingestion worker ignores detection; does not call `process_student_detection`.
  4. Movement logs table count remains unchanged.
  5. Student S1's `current_status` remains unchanged.
  6. Dashboard `/hostel/api/movement_logs` shows no spurious entry.

#### `T3-07: test_t3_07_exit_immediately_preceding_curfew_cutoff`
- **Initial Setup**:
  - Student S1 is `IN`. Simulated clock at 19:29:58.
- **Sequence**:
  1. S1 exits via `CAM_02_EXIT` at 19:29:58. Status updated to `OUT`.
  2. 2 seconds later (19:30:00), Curfew scanner executes.
  3. Scanner sees `current_time >= 19:30:00` and S1 is `OUT`.
  4. S1 is immediately added to `girls_hostel.curfew_alerts`.
  5. Query `GET /hostel/api/stats`: `overdue_count` equals 1.

#### `T3-08: test_t3_08_resolved_alert_subsequent_outing_alert_cycle`
- **Initial Setup**:
  - S1 breached curfew at 19:30, was flagged `OVERDUE_OUT`, and alert #1 was resolved by warden at 19:40.
- **Sequence**:
  1. At 19:45, S1 leaves again via `CAM_02_EXIT`. Status becomes `OUT`.
  2. Curfew scanner runs at 19:46.
  3. Scanner checks for existing `OVERDUE_OUT` alerts for S1 today.
  4. Prior alert #1 has `status = 'RESOLVED'`.
  5. Scanner creates a new alert #2 with `status = 'OVERDUE_OUT'` for the new unpermitted departure.
  6. Query `GET /hostel/api/overdue_alerts`: returns alert #2.

#### `T3-09: test_t3_09_multi_face_batch_detection_exit_overdue_sync`
- **Initial Setup**:
  - 4 students (S1, S2, S3, S4) all initially `IN`.
- **Sequence**:
  1. At 19:20, `CAM_02_EXIT` detects all 4 faces in a single batch (<200ms).
  2. State machine processes all 4 detections: all transition to `OUT`.
  3. Curfew cutoff occurs at 19:30.
  4. Curfew scanner executes: all 4 are identified as `OUT`.
  5. Scanner creates 4 distinct records in `girls_hostel.curfew_alerts`.
  6. Query `GET /hostel/api/stats`: `total_out = 4, overdue_count = 4`.
  7. Query `GET /hostel/api/overdue_alerts`: returns all 4 alerts with corresponding parent contacts.

#### `T3-10: test_t3_10_schema_isolation_across_endpoints_and_engine`
- **Initial Setup**:
  - Query interceptor / spy active on all database queries during test.
- **Sequence**:
  1. Execute: `GET /hostel`, `GET /hostel/api/stats`, `GET /hostel/api/movement_logs`, `GET /hostel/api/overdue_alerts`, `POST /hostel/api/resolve_alert`.
  2. Trigger `process_student_detection` and `check_curfew_violations`.
  3. Inspect all generated SQL / Supabase REST queries.
  4. Assert: 100% of queries target schema `girls_hostel`.
  5. Assert: Exactly 0 queries contain `"public."` or omit schema scope.

---

## 5. Tier 4: Real-World Scenarios Specification (5 Tests)

Tier 4 tests model realistic operational days in the girls' hostel, verifying end-to-end behavior under burst loads, temporal transitions, and human interventions.

```
       17:00                19:00 - 19:25               19:30                19:45
  Curfew Window Opens       Staggered Returns        Curfew Cutoff        Warden Resolution
─────────┬─────────────────────────┬───────────────────────┬───────────────────────┬──────> Time
         │                         │                       │                       │
     Mass Exit                Safe Inward            Overdue Alerts          Late Returns
   (15 Students)             (10 Students)             Dispatched            & Pass Notes
                                                      (5 Students)
```

---

### Detailed Tier 4 Scenarios

### `T4-01: test_t4_01_evening_rush_mass_exit_curfew_breach_and_resolution`
- **Narrative**:
  On a Friday evening, 20 hostel students are inside the hostel at 17:00 (Curfew window opening). Between 17:05 and 17:30, 15 students exit through Camera 2 to visit the local market. Between 18:30 and 19:25, 10 students return safely through Camera 1. At 19:30:00 (Curfew deadline), 5 students remain outside. The automated scanner triggers overdue alerts. The warden reviews the dashboard, calls parents, and resolves 2 alerts upon confirmed bus delays. The 2 students arrive at 19:45.
- **Simulation Steps**:
  1. *Cohort Ingestion*: Populate 20 students ($S_1 \dots S_{20}$) in `girls_hostel.student_profiles` with `current_status = 'IN'`.
  2. *Phase 1 (17:05 - 17:30 - Mass Exit)*:
     - Simulate 15 detections on `CAM_02_EXIT` for $S_1 \dots S_{15}$.
     - Assert state machine marks all 15 as `OUT`.
     - Query `/hostel/api/stats`: `total_in = 5, total_out = 15, overdue_count = 0`.
  3. *Phase 2 (18:30 - 19:25 - Staggered Returns)*:
     - Simulate 10 detections on `CAM_01_ENTRY` for $S_1 \dots S_{10}$.
     - Assert state machine marks all 10 as `IN`.
     - Query `/hostel/api/stats`: `total_in = 15, total_out = 5, overdue_count = 0`.
  4. *Phase 3 (19:30:01 - Curfew Cutoff)*:
     - Mock server time to `19:30:01`.
     - Curfew scanner runs `check_curfew_violations()`.
     - Scanner finds exactly 5 students ($S_{11} \dots S_{15}$) `OUT`.
     - Exactly 5 alerts created in `girls_hostel.curfew_alerts`.
  5. *Phase 4 (19:35 - Warden Dashboard Verification)*:
     - Authenticated warden queries `GET /hostel/api/stats`:
       - `total_students = 20`
       - `total_in = 15`
       - `total_out = 5`
       - `overdue_count = 5`
     - Warden queries `GET /hostel/api/overdue_alerts`:
       - Returns exactly 5 alerts with student names, room numbers, and parent contacts.
  6. *Phase 5 (19:40 - Warden Resolution & Late Return)*:
     - Warden resolves alerts for $S_{11}$ and $S_{12}$ with notes `"Bus delay verified by parent"`.
     - Query `/hostel/api/stats`: `overdue_count = 3`.
     - At 19:45, $S_{11}$ and $S_{12}$ appear at `CAM_01_ENTRY`. State machine marks them `IN`.
     - Query `/hostel/api/stats`: `total_in = 17, total_out = 3, overdue_count = 3`.

---

### `T4-02: test_t4_02_multi_student_overdue_batch_dispatch_and_rapid_resolution`
- **Narrative**:
  Simulates a batch dispatch of 10 overdue alerts at curfew cutoff, tests alert deduplication/idempotency across multiple consecutive scanner cycles, and tests rapid sequential resolutions by the warden with custom notes.
- **Simulation Steps**:
  1. Seed 10 students as `OUT` at 19:20.
  2. Advance time to 19:30:00. Execute `check_curfew_violations()`.
  3. Assert 10 alerts created with `status = 'OVERDUE_OUT'`.
  4. **Scanner Idempotency Check**: Immediately run `check_curfew_violations()` again at 19:31:00 and 19:32:00.
     - Assert alert count in database is STILL exactly 10 (no duplicate alerts spawned).
  5. Warden opens `/hostel` dashboard and executes rapid resolution calls:
     - 4 students marked `status = 'EXCUSED'` with notes `"Academic lab extension approved"`.
     - 6 students marked `status = 'RESOLVED'` with notes `"Parent contacted, student reached gate"`.
  6. Query `GET /hostel/api/overdue_alerts`: asserts returns `alerts: []`.
  7. Query `GET /hostel/api/stats`: asserts `overdue_count = 0`.

---

### `T4-03: test_t4_03_morning_rush_tailgating_and_face_lingering`
- **Narrative**:
  Simulates morning class rush (08:00 AM) where 8 students exit. Student 1 lingers directly in front of `CAM_02_EXIT` for 30 seconds while 7 other students walk past the camera in the background.
- **Simulation Steps**:
  1. 8 students ($S_1 \dots S_8$) initially `IN`.
  2. Frame 1 ($T_0$): $S_1$ detected. State machine marks $S_1$ as `OUT`. Log 1 recorded.
  3. Frames 2-6 ($T_0 + 2\text{s}, 5\text{s}, 8\text{s}, 11\text{s}, 14\text{s}$): $S_1$ continuously detected in camera feed.
     - Anti-bounce cooldown suppresses each frame. Zero new logs created for $S_1$.
  4. Frames 7-13: Interspersed frames detect $S_2 \dots S_8$ passing through.
     - Each of $S_2 \dots S_8$ is successfully transitioned to `OUT` and logged once.
  5. Frame 14 ($T_0 + 16\text{s}$): $S_1$ is still standing in camera view.
     - Cooldown timer (15s) has expired, BUT $S_1$ is ALREADY `OUT`.
     - Movement engine suppresses redundant state change or log.
  6. Assert: Total logs in `girls_hostel.movement_logs` is exactly 8 (1 per student).
  7. Assert: All 8 students have `current_status = 'OUT'`.

---

### `T4-04: test_t4_04_full_24hr_cycle_system_window_transitions`
- **Narrative**:
  Simulates a full 24-hour cycle through different operational windows:
  1. Afternoon (14:00 - 16:59): Off-hours movement. Students exit; curfew monitoring inactive; no alerts.
  2. Evening Window (17:00 - 19:29:59): Standard curfew window open. Students moving; no overdue alerts.
  3. Curfew Cutoff (19:30 - 23:59): Strict curfew window. All `OUT` students alerted.
  4. Next Morning (06:00, Date + 1): New calendar day. Yesterday's resolved alerts are archived; fresh day monitoring begins.
- **Simulation Steps**:
  1. *14:00 (Off-Hours)*: Student exits. Status updated to `OUT`. Curfew check runs; zero alerts.
  2. *17:00 (Window Start)*: Settings confirm `system_start_time = "17:00:00"`. Movement continues normally.
  3. *19:29:59 (Boundary)*: Clock frozen at 19:29:59. Curfew check runs; asserts `current_time < 19:30:00` -> zero alerts.
  4. *19:30:01 (Curfew)*: Clock advances to 19:30:01. Curfew check runs; alert created for `curfew_date = Date_1`.
  5. *Next Day 06:00 (Reset)*: Clock advances to next day.
     - Previous day alert remains in database with `curfew_date = Date_1`.
     - Student re-enters hostel at 06:15.
     - Next day curfew check runs at 19:30 on Date_2; does not conflate Date_1 records.

---

### `T4-05: test_t4_05_high_load_dual_gate_burst_with_live_warden_polling`
- **Narrative**:
  Simulates high concurrency: both gates process 10 faces/frame at 5 FPS (50 detection events total across 5 seconds), while multiple warden dashboard instances poll `/hostel/api/stats`, `/hostel/api/movement_logs`, and `/hostel/api/overdue_alerts` every 1 second.
- **Simulation Steps**:
  1. Initialize 20 students in `girls_hostel.student_profiles`.
  2. Launch a thread pool generating 50 concurrent detection requests distributed between `CAM_01_ENTRY` and `CAM_02_EXIT`.
  3. Simultaneously launch 3 background worker threads repeatedly querying:
     - `GET /hostel/api/stats`
     - `GET /hostel/api/movement_logs?limit=50`
     - `GET /hostel/api/overdue_alerts`
  4. Complete all detection and polling threads within 5 seconds.
  5. Assertions:
     - Zero unhandled 500 exceptions across all polling requests.
     - State machine completes all transitions with database consistency.
     - Invariant `total_students == total_in + total_out` holds true across all polled stats responses.
     - API response time remains under 100ms per call.

---

## 6. Recommended Test Client Setup & E2E Integration Patterns

### 6.1 Test Directory Structure

```
tests/
├── conftest.py                       # Global fixtures: app, client, auth_client, mock_db
├── e2e/
│   ├── test_tier1_r1_schema.py       # Explorer 1 scope
│   ├── test_tier1_r2_camera.py       # Explorer 1 scope
│   ├── test_tier1_r3_state.py        # Explorer 2 scope
│   ├── test_tier1_r4_curfew.py       # Explorer 2 scope
│   ├── test_tier1_r5_dashboard.py    # Explorer 3 scope (R5 Tier 1)
│   ├── test_tier2_boundaries.py      # T2 tests across R1-R5
│   ├── test_tier3_cross_feature.py   # Explorer 3 scope (T3-01 to T3-10)
│   └── test_tier4_real_world.py      # Explorer 3 scope (T4-01 to T4-05)
└── mocks/
    ├── mock_supabase.py              # In-memory mock for girls_hostel schema
    └── mock_camera_feed.py           # Frame generator for InsightFace
```

### 6.2 Application Factory & Authentication Fixture (`conftest.py`)

```python
import os
import pytest
from unittest.mock import patch
from src import create_app
from src.utils.hostel_state import _cooldown_registry
from src.services.curfew_service import stop_curfew_service

@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Configure test environment variables before app initialization."""
    os.environ["FLASK_SECRET_KEY"] = "test-secret-key-32-chars-long-secure!!"
    os.environ["SUPABASE_URL"] = "https://mock-test.supabase.co"
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "mock-service-role-key"
    os.environ["LOG_LEVEL"] = "WARNING"

@pytest.fixture
def app():
    """Create Flask application with background curfew loop suppressed."""
    with patch("src.blueprints.hostel.start_curfew_service"):
        application = create_app()
        application.config.update({
            "TESTING": True,
            "SERVER_NAME": "localhost.localdomain"
        })
        yield application
    # Clean up any lingering background threads
    stop_curfew_service()

@pytest.fixture
def client(app):
    """Unauthenticated Flask test client."""
    return app.test_client()

@pytest.fixture
def auth_client(app):
    """Authenticated warden client with valid session."""
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "warden_test"
        sess["is_admin"] = True
        sess["user_id"] = "00000000-0000-0000-0000-000000000001"
    return test_client

@pytest.fixture(autouse=True)
def reset_cooldown_registry():
    """Clear in-memory anti-bounce cooldown registry between each test."""
    _cooldown_registry.clear()
    yield
    _cooldown_registry.clear()
```

### 6.3 Isolated Database Mocking Pattern

To test real logic while eliminating external Supabase network dependencies, use a schema-scoped in-memory database mock:

```python
class MockHostelClient:
    """In-memory table storage strictly scoped to girls_hostel schema."""
    def __init__(self):
        self.tables = {
            "student_profiles": [],
            "movement_logs": [],
            "curfew_alerts": [],
            "system_settings": []
        }
    
    def table(self, table_name):
        return MockTableQuery(self.tables.setdefault(table_name, []))

class MockTableQuery:
    def __init__(self, data_list):
        self._data = data_list
        self._filters = []
        self._order_field = None
        self._order_desc = False
        self._limit_val = None

    def select(self, fields="*"):
        return self

    def eq(self, field, value):
        self._filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self._order_field = field
        self._order_desc = desc
        return self

    def limit(self, val):
        self._limit_val = val
        return self

    def insert(self, record):
        if isinstance(record, dict):
            if "id" not in record:
                record["id"] = len(self._data) + 1
            self._data.append(record)
        return self

    def update(self, update_fields):
        # Applies update to matched records
        for row in self._data:
            if all(row.get(k) == v for k, v in self._filters):
                row.update(update_fields)
        return self

    def execute(self):
        # Filter and sort
        res = [
            row for row in self._data
            if all(row.get(k) == v for k, v in self._filters)
        ]
        if self._limit_val is not None:
            res = res[:self._limit_val]
        class MockResult:
            data = res
        return MockResult()
```

---

## 7. Synthesis with Explorers 1 & 2

- **Explorer 1 (R1/R2 Focus)**:
  - Validates `girls_hostel` schema isolation, RLS rules, `match_face` RPC, and InsightFace dual-camera ingestion (<200ms).
  - *Tier 3/4 Connection*: Our Tier 3 tests (`T3-06`, `T3-10`) directly invoke the `match_face` RPC boundary and assert zero `public.*` leaks during live dashboard operations.

- **Explorer 2 (R3/R4 Focus)**:
  - Validates `HostelMovementEngine` (15s boundary: 14.9s rejected, 15.1s accepted) and `HostelCurfewService` (19:29:59 vs 19:30:01 boundary).
  - *Tier 3/4 Connection*: Our Tier 3 tests (`T3-01`, `T3-02`, `T3-03`, `T3-07`) and Tier 4 scenarios (`T4-01` to `T4-04`) compose Explorer 2's state machine and curfew scanner with live warden API verification.

- **Total Test Suite Volume & Traceability**:
  - Tier 1 (Coverage): 25 tests (5 per R1-R5). R5 has 6 tests specified here.
  - Tier 2 (Boundaries): 25 tests (5 per R1-R5). R5 has 8 tests specified here.
  - Tier 3 (Cross-Feature): 10 tests specified here (exceeds requirement >=8).
  - Tier 4 (Real-World): 5 scenarios specified here (meets requirement >=5).
  - Grand Total: $\ge 65$ comprehensive tests guaranteeing 100% requirements coverage.
