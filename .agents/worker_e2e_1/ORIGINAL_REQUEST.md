## 2026-09-09T05:03:13Z
You are Worker 1 (E2E Test Suite Implementer).
Working directory: /home/dell/BioSecure AI - GIrls Hostel/.agents/worker_e2e_1
Your parent is Sub-Orchestrator E2E (`sub_orch_e2e`).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Read these reference files:
- /home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator/PROJECT.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/sub_orch_e2e/SCOPE.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_1/analysis.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_2/analysis.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_3/analysis.md
- /home/dell/BioSecure AI - GIrls Hostel/scripts/girls_hostel_schema.sql
- /home/dell/BioSecure AI - GIrls Hostel/src/utils/hostel_db.py
- /home/dell/BioSecure AI - GIrls Hostel/src/utils/hostel_state.py
- /home/dell/BioSecure AI - GIrls Hostel/src/services/curfew_service.py
- /home/dell/BioSecure AI - GIrls Hostel/src/blueprints/hostel.py

Your Tasks:
1. Environment Verification:
   - Check if pytest is installed in `.venv`. If not, install pytest (`.venv/bin/pip install pytest`).
2. Implement Test Harness & Fixtures in `tests/conftest.py`:
   - An in-memory MockSupabaseHostelClient that strictly enforces schema="girls_hostel", implements real table operations (student_profiles, movement_logs, curfew_alerts, system_settings), implements real cosine vector similarity for girls_hostel.match_face RPC, and raises an exception if any query accesses the public schema or omits girls_hostel schema scoping.
   - Flask test client fixture with authenticated warden session (`logged_in=True`, `username='warden'`) and unauthenticated client.
   - Frozen time / time travel helper using standard library unittest.mock to test microsecond-accurate time boundaries.
   - Autouse fixture clearing `_cooldown_registry` in `src.utils.hostel_state` between test cases.
   - Fixture to stop background curfew service thread during test runs.
3. Implement 4-Tier Test Suite under `tests/e2e/`:
   - `tests/e2e/test_tier1_features.py`:
     * R1: Schema isolation, RLS enabled on all 4 tables, match_face RPC cosine search, zero public.* references, CRUD isolation (>=5 tests).
     * R2: Dual camera simultaneous ingestion (CAM_01_ENTRY, CAM_02_EXIT), multi-face detection (up to 10 faces), <200ms latency validation, 512D unit normalization (>=5 tests).
     * R3: Movement state machine: CAM_02 Exit -> OUT, CAM_01 Entry -> IN, 15s anti-bounce cooldown (>=5 tests).
     * R4: Curfew window schedule (17:00-19:30), overdue scanning, OVERDUE_OUT alert generation, parent contact alert (>=5 tests).
     * R5: Warden dashboard endpoints (/hostel, /hostel/api/stats, /hostel/api/movement_logs, /hostel/api/overdue_alerts, /hostel/api/resolve_alert) (>=5 tests).
     Total Tier 1 tests: >=25 tests.
   - `tests/e2e/test_tier2_boundaries.py`:
     * R1 boundaries: Cosine threshold boundary (0.3999 excluded vs 0.4000 included), orthogonal (0.0), antipodal (-1.0), top-k limits, null embeddings, foreign key cascade deletion (>=5 tests).
     * R2 boundaries: 0 faces / empty frame, overflow (>10 faces), extreme face sizes, extreme yaw poses, corrupted/None frames, camera reconnect (>=5 tests).
     * R3 boundaries: Cooldown boundary (14.9s rejected vs 15.1s accepted), cross-camera cooldown independence, pre-state debouncing (already IN/already OUT), burst face readings (>=5 tests).
     * R4 boundaries: Curfew boundary (19:29:59 not overdue vs 19:30:00/19:30:01 overdue), off-hours pre-17:00, alert idempotency on multiple scans, missing parent contact handling, midnight boundary (>=5 tests).
     * R5 boundaries: Unauthenticated access 302 redirect, missing alert_id 400 error, malformed JSON, query limit parameters, rapid resolution calls (>=5 tests).
     Total Tier 2 tests: >=25 tests.
   - `tests/e2e/test_tier3_combinations.py`:
     * >=8 cross-feature combination tests (implement 10 tests as planned by Explorer 3):
       1. Departure & Return Lifecycle Sync
       2. Lingering at gate before curfew cutoff
       3. Curfew breach -> Warden alert view -> Alert resolution -> subsequent departure
       4. Dual gate simultaneous concurrent ingestion
       5. Multi-camera cooldown isolation (Exit then immediate Entry allowed)
       6. Low biometric similarity rejection (<0.40) -> state remains unchanged -> no movement log
       7. Curfew cutoff race condition (Exit at 19:29:58 -> scan at 19:30:00 -> alert logged)
       8. Alert resolution with re-entry before curfew reset
       9. Multi-face batch ingestion with mixed states -> batch alert generation
       10. Schema isolation verification under full system load (confirm zero calls to public schema)
   - `tests/e2e/test_tier4_scenarios.py`:
     * >=5 real-world scenarios:
       1. Friday Evening Rush & Curfew Breach (20 students: 15 exit before 19:30, 10 return, 5 overdue past 19:30, 2 return late at 20:00, warden resolves)
       2. Multi-Student Overdue Alert Batch Dispatch (10 overdue students, scanner idempotency over multiple scans, warden bulk review & resolution)
       3. Morning Gate Congestion & Lingering (tailgating and face lingering on exit camera, 8 students)
       4. 24-Hour Cycle System Window Transitions (Off-hours 14:00, Start 17:00, Cutoff 19:30, Midnight 01:00, Next-day 07:00 reset)
       5. High-Load Dual-Gate Burst Stress (10 faces/frame simultaneous on both gates, 50 detections, with concurrent dashboard polling)
   Total tests: >=63 tests (target 65 tests).
4. Documentation Deliverables:
   - Create `TEST_INFRA.md` at project root documenting:
     * Test philosophy (opaque-box, requirement-driven, 100% schema isolation)
     * Feature inventory mapping requirements R1-R5 to test tiers
     * Test runner commands and execution instructions
     * Directory layout
     * Coverage thresholds
   - Run the full test suite using `.venv/bin/pytest tests/e2e -v`. Confirm all tests pass 100%.
   - Create `TEST_READY.md` at project root summarizing:
     * Test runner command (`pytest tests/e2e`)
     * Tier-by-tier test count and status (100% passing)
     * Feature checklist table
5. Write `progress.md` and `handoff.md` in your working directory (`/home/dell/BioSecure AI - GIrls Hostel/.agents/worker_e2e_1/`) with full test execution outputs, and notify parent.
