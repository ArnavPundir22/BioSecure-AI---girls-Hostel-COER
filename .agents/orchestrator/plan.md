# Project Execution Plan: BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System

## Strategy Overview
Adhere strictly to the Project Pattern with Dual-Track Architecture:
1. **E2E Testing Track**: Independent opaque-box test suite development based strictly on `ORIGINAL_REQUEST.md` (Tiers 1-4: >=55 tests). Publishes `TEST_READY.md`.
2. **Implementation Track**: Sequential milestone delivery (M1 -> M2 -> M3 -> M4 -> M5) followed by Final Milestone (Phase 1: 100% E2E test pass; Phase 2: Tier 5 adversarial coverage hardening).

Each milestone executes the mandatory loop:
`Explorer (3 agents)` -> `Worker (1 agent)` -> `Reviewer (2 agents)` -> `Challenger (2 agents)` -> `Forensic Auditor (1 agent)` -> `Gate (Binary Veto on Integrity Violation)`.

## Milestones Roadmap

### Track 1: E2E Testing Suite (Requirements-Driven)
- **Goal**: Implement opaque-box test runner and test cases for Tiers 1-4.
  - Tier 1: Feature Coverage (>=5 tests per feature, minimum 25 tests)
  - Tier 2: Boundary & Corner Cases (>=5 tests per feature, minimum 25 tests)
  - Tier 3: Cross-Feature Combinations (Pairwise coverage)
  - Tier 4: Real-World Hostel Scenarios (Late night exit, curfew cutoff batch overdue, simultaneous entry/exit, parent contact dispatch)
- **Deliverable**: `tests/e2e/`, `TEST_INFRA.md`, and `TEST_READY.md`.

### Track 2: Implementation Milestones

#### Milestone 1 (M1): Isolated PostgreSQL Schema Migration (`girls_hostel`)
- Update `scripts/girls_hostel_schema.sql` to include Supabase Row Level Security (RLS) on all `girls_hostel` tables (`student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings`).
- Ensure HNSW index and `girls_hostel.match_face` RPC are fully defined.
- Update/implement `src/utils/hostel_db.py` to interact strictly with `girls_hostel.*`.
- Absolute zero references/reads/writes to `public.student_profiles` or `public.attendance_logs`.

#### Milestone 2 (M2): Dual Camera Ingestion & Multi-Face Detection
- Implement `src/services/hostel_camera_service.py` to ingest Camera 1 (Entry) and Camera 2 (Exit) streams simultaneously without dropping frames.
- Integrate InsightFace for multi-face detection (RetinaFace + ArcFace 512D) processing up to 10 faces concurrently with sub-200ms batch latency.
- Handle dummy/simulated camera video streams for test environments and headless execution.

#### Milestone 3 (M3): Movement State Machine & Cooldown Engine
- Implement `src/utils/hostel_state.py`:
  - Camera 2 (Exit) detects student currently `IN` -> transitions state to `OUT`, inserts movement log `direction='OUT'`.
  - Camera 1 (Entry) detects student currently `OUT` -> transitions state to `IN`, inserts movement log `direction='IN'`.
  - 15-second anti-bounce cooldown per student per camera stream.
  - Integration with `src/utils/hostel_db.py`.

#### Milestone 4 (M4): Curfew Schedule & Overdue Alert Scanner
- Implement `src/services/curfew_service.py`:
  - Configurable window settings (default 17:00 start, 19:30 curfew cutoff).
  - Background periodic scan: queries all students with `current_status = 'OUT'` when current time >= 19:30.
  - Writes `OVERDUE_OUT` alerts into `girls_hostel.curfew_alerts`.
  - Sends email alert via SMTP with parent contact details.
  - Prevents redundant duplicate alerts for the same student on the same date.

#### Milestone 5 (M5): Warden Dashboard & Control Center UI
- Implement `src/blueprints/hostel.py`, `src/templates/hostel_dashboard.html`, `src/static/css/hostel_dashboard.css`, and `src/static/js/hostel_dashboard.js`.
- Features:
  - Dark glassmorphic modern UI at `/hostel`.
  - Dual live stream viewer cards (Camera 1 Entry & Camera 2 Exit).
  - Live movement logs table with direction badges (`IN` green, `OUT` amber).
  - Active overdue alert panel highlighting overdue students, room numbers, parent contact details, and time elapsed.
  - Alert resolution controls (`RESOLVE`, `EXCUSE`).
  - Real-time stats header.

#### Final Milestone: E2E Acceptance & Adversarial Hardening
- Phase 1: Run 100% of E2E tests (Tiers 1-4) across the integrated application.
- Phase 2: Challenger adversarial stress-testing (Tier 5) to test high-concurrency race conditions, embedding drift edge cases, and network drop recovery.
- Forensic Auditor integrity sweep to guarantee zero mock-bypasses or public schema leaks in production paths.
- Final completion handoff report to Sentinel.
