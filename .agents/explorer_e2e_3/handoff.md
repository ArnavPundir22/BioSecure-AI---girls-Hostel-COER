# Handoff Report: E2E Test Architecture (R5 & Tier 3/4 Scenarios Focus)

**Agent**: Explorer 3 (`explorer_e2e_3`)  
**Target Recipient**: Sub-orchestrator (`sub_orch_e2e`)  
**Timestamp**: 2026-09-09T05:05:00Z  
**Type**: Hard Handoff (Investigation & Architecture Complete)

---

## 1. Observation

Direct code observations from inspecting the codebase:

1. **Warden Dashboard & API Routes (`src/blueprints/hostel.py:15-94`)**:
   - `hostel_bp` is registered with `url_prefix="/hostel"`.
   - `GET /hostel/` renders `templates/hostel_dashboard.html` (lines 23-26).
   - `GET /hostel/api/stats` returns JSON with keys `total_students`, `total_in`, `total_out`, `overdue_count`, and `curfew_window` ("17:00 - 19:30") (lines 28-48).
   - `GET /hostel/api/movement_logs` accepts query parameter `limit` (default: 50) and returns `{"logs": [...]}` (lines 50-59).
   - `GET /hostel/api/overdue_alerts` returns `{"alerts": [...]}` of all active alerts with `status == 'OVERDUE_OUT'` (lines 61-69).
   - `POST /hostel/api/resolve_alert` expects JSON `{"alert_id": <id>, "notes": <optional_notes>}`. It returns 400 if `alert_id` is missing, and updates `curfew_alerts` with `status = 'RESOLVED'`, `resolved_at = 'now()'`, and `notes` (lines 71-93).
   - Line 18-21: `start_curfew_service()` is invoked at the blueprint module top-level upon import, launching a background scanner thread.

2. **Authentication Middleware (`src/__init__.py:127-142`)**:
   - `require_login()` runs before every request:
     ```python
     public_paths = {"/login", "/favicon.ico", "/healthz", "/auth/callback"}
     if request.path.startswith("/static/") or request.path.startswith("/login/oauth/") or request.path in public_paths:
         return None
     if "logged_in" not in session:
         return redirect(url_for("auth.login"))
     ```
   - Neither `/hostel` nor `/hostel/api/*` are in `public_paths`. Any unauthenticated request receives a 302 redirect to `/login`.

3. **In-Memory Cooldown State (`src/utils/hostel_state.py:16-59`)**:
   - Cooldown is stored in a module-level dictionary `_cooldown_registry: Dict[str, Tuple[str, datetime]] = {}`.
   - `COOLDOWN_SECONDS = 15`.
   - Cooldown check evaluates `if last_cam == camera_id and time_elapsed < COOLDOWN_SECONDS: return None`.
   - Cooldown is isolated per camera: a detection on `CAM_02_EXIT` does NOT block a subsequent detection on `CAM_01_ENTRY`.

4. **Curfew Cutoff & Scanner (`src/services/curfew_service.py:20-68`)**:
   - `DEFAULT_CURFEW_END = dtime(19, 30, 0)` (7:30 PM).
   - Condition: `if current_time >= DEFAULT_CURFEW_END:` queries `girls_hostel.student_profiles` for `current_status = 'OUT'`.
   - Idempotency query filters by `.eq("student_id", student_id).eq("curfew_date", today_str).eq("status", "OVERDUE_OUT")`.

5. **Test Environment State**:
   - `tests/` directory does not currently exist.
   - `pytest` is not yet installed in `.venv`. Standard library `unittest` is available; `pytest` should be installed for test execution.

---

## 2. Logic Chain

1. **Authentication in Test Client (Observations 1 & 2)**:
   - Because `require_login()` intercepts all requests without `"logged_in" in session`, any opaque-box test evaluating warden dashboard endpoints MUST either:
     a) Explicitly assert that unauthenticated requests are redirected with HTTP 302 to `/login` (security boundary verification), or
     b) Use an authenticated test client fixture (`sess["logged_in"] = True`, `sess["username"] = "warden"`) for feature endpoints.
2. **Background Thread Management (Observation 1)**:
   - Because `src/blueprints/hostel.py` executes `start_curfew_service()` upon module import, test execution without mocking would spawn an active daemon thread running every 60 seconds against the database.
   - Therefore, the test runner must either patch `start_curfew_service` during application setup or invoke `stop_curfew_service()` during fixture teardown.
3. **State Engine Isolation (Observation 3)**:
   - Because `_cooldown_registry` is stored in global process memory, consecutive tests executing state machine transitions would suffer test pollution if 15 seconds have not elapsed in real time.
   - Therefore, an `autouse` pytest fixture must call `_cooldown_registry.clear()` before and after every test.
4. **Cross-Feature Integration (Observations 1, 3, 4)**:
   - Real-world hostel workflows involve the sequential interaction of:
     Biometric Face Match $\to$ Movement State Engine $\to$ Isolated Database Persistence $\to$ Curfew Background Scanner $\to$ Warden Dashboard REST API $\to$ Alert Resolution.
   - Opaque-box Tier 3 tests must test this full chain without inspecting internal variables, verifying only HTTP/API and database outcomes.
5. **Real-World Scenarios (Observations 1, 3, 4)**:
   - Scenarios like the Friday Evening Rush (mass exit before curfew, staggered return, curfew cutoff breach, late arrival, and warden resolution) exercise all 5 core requirements (R1-R5) under realistic load and time progression.

---

## 3. Caveats

1. **RTSP Live Video Feeds**: The dashboard HTML contains video container cards for `CAM 01: ENTRY GATE` and `CAM 02: EXIT GATE`, but dedicated streaming routes (`/hostel/stream/entry`, `/hostel/stream/exit`) are not yet present in `src/blueprints/hostel.py`. Tests currently verify the dashboard HTML structure; stream endpoints will be tested once implemented in M2/M5.
2. **Naive Local Datetime in Curfew Service**: `curfew_service.py` uses `datetime.now().time()`, which is timezone-naive local system time. In tests, time manipulation must patch `datetime.now()` consistently.
3. **Database Client Mocking**: In the absence of a live Supabase PostgreSQL server during offline test execution, an in-memory schema-scoped mock client (`MockHostelClient`) is recommended to ensure fast, deterministic CI execution while maintaining 100% schema isolation fidelity.

---

## 4. Conclusion

1. Formulated complete test specifications for **R5 (Warden Dashboard)**:
   - **Tier 1 (Feature Coverage)**: 6 test cases (`test_r5_t1_01` to `test_r5_t1_06`).
   - **Tier 2 (Boundaries & Security)**: 8 test cases (`test_r5_t2_01` to `test_r5_t2_08`).
2. Formulated complete test specifications for **Tier 3 (Cross-Feature Combinations)**:
   - **10 test cases** (`T3-01` to `T3-10`), exceeding the minimum requirement of 8.
   - Covers: departure/return lifecycle sync, anti-bounce lingering before curfew, curfew breach to warden resolution, dual-gate concurrent ingestion, multi-camera cooldown isolation, biometric rejection propagation, cutoff race conditions, resolution re-entry cycles, multi-face batch alerting, and schema isolation audit.
3. Formulated complete test specifications for **Tier 4 (Real-World Scenarios)**:
   - **5 end-to-end temporal simulations** (`T4-01` to `T4-05`):
     - `T4-01`: Friday Evening Rush & Curfew Breach (20 students: 15 exit, 10 return, 5 overdue, 2 late returns, warden resolution).
     - `T4-02`: Multi-Student Overdue Alert Batch Dispatch (10 students), scanner idempotency, and rapid warden resolution (`RESOLVED` vs `EXCUSED`).
     - `T4-03`: Morning Gate Congestion & Anti-Bounce Face Lingering (30s lingering on Exit camera, 8 students).
     - `T4-04`: Full 24-Hour Cycle System Window Transitions (Off-hours 14:00, Release 17:00, Curfew 19:30, Date+1 reset).
     - `T4-05`: High-Load Stress Scenario (Dual gates burst: 10 faces/frame @ 5 FPS, 50 detections) with concurrent warden UI polling.
4. Delivered comprehensive Flask `test_client` and fixture architecture in `analysis.md`.

---

## 5. Verification Method

1. **Inspect Analysis Report**:
   - Read `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_3/analysis.md`.
   - Verify all test matrices, endpoint schemas, and scenario steps match `PROJECT.md` and `SCOPE.md`.
2. **Verify Route Existence**:
   - Check `src/blueprints/hostel.py` to confirm routes `/`, `/api/stats`, `/api/movement_logs`, `/api/overdue_alerts`, `/api/resolve_alert`.
3. **Verify Auth Middleware**:
   - Check `src/__init__.py:127-142` to confirm `require_login()` behavior and public paths list.
4. **Execution Validation (for implementers)**:
   - When tests are written under `tests/e2e/`, run:
     ```bash
     pytest tests/e2e/test_tier1_r5_dashboard.py tests/e2e/test_tier3_cross_feature.py tests/e2e/test_tier4_real_world.py -v
     ```
