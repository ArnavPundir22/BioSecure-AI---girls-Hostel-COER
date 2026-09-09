# Original User Request

## 2026-09-09T04:58:00Z

You are the E2E Testing Sub-Orchestrator for the BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System project.

Parent Conversation ID: c38ce4d6-88b6-48c3-90d9-1004889c5440 (Wait, orchestrator caller conversation ID: 0d3371b1-47b5-4496-8d28-86e91a40d7fc. Report to 0d3371b1-47b5-4496-8d28-86e91a40d7fc)
Workspace root: /home/dell/BioSecure AI - GIrls Hostel
Your working directory: /home/dell/BioSecure AI - GIrls Hostel/.agents/sub_orch_e2e
Reference files:
- /home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator/PROJECT.md

Scope:
Design, implement, and verify an independent, opaque-box E2E test suite strictly derived from user requirements in ORIGINAL_REQUEST.md.

Mandatory Deliverables:
1. Complete E2E test suite under `tests/e2e/` using pytest.
2. 4-Tier Test Coverage:
   - Tier 1: Feature Coverage (>=5 test cases per feature across R1-R5, minimum 25 tests)
     * R1: Schema isolation, RLS enabled, match_face RPC, zero public.* reads/writes
     * R2: Dual camera simultaneous ingestion, multi-face detection (up to 10 faces), <200ms latency
     * R3: Movement state machine: CAM_02 Exit -> OUT, CAM_01 Entry -> IN, 15s anti-bounce cooldown
     * R4: Curfew window schedule (17:00-19:30), overdue scanning, OVERDUE_OUT alert generation, parent contact alert
     * R5: Warden dashboard endpoints (/hostel, /hostel/stream/*, /hostel/api/*, alert resolution)
   - Tier 2: Boundary & Corner Cases (>=5 test cases per feature, minimum 25 tests)
     * Cooldown boundary (14.9s rejected, 15.1s accepted)
     * Curfew boundary (19:29:59 not overdue, 19:30:01 overdue)
     * Rapid repeated faces, extreme face sizes/orientations
     * Missing parent contact / malformed payload handling
     * Idempotent alert creation on multiple scans
   - Tier 3: Cross-Feature Combinations (>=8 tests)
     * Entry -> Cooldown -> Curfew transition
     * Face match -> State change -> Alert resolution -> Subsequent exit
     * High concurrent detections at both gates simultaneously
   - Tier 4: Real-World Scenarios (>=5 tests)
     * Evening mass exit before curfew, late return after curfew trigger
     * Multi-student overdue alert batch dispatch with warden dashboard verification
3. Total test cases >= 63 tests.
4. Test Infrastructure:
   - Create `TEST_INFRA.md` at project root documenting architecture, features, and run commands.
   - Run tests and ensure all tests pass.
   - Publish `TEST_READY.md` at project root summarizing test count, tiers, and run instructions (`pytest tests/e2e`).

Follow the Orchestrator Procedure:
- Initialize BRIEFING.md and progress.md in your working directory.
- Dispatch Worker (`teamwork_preview_worker`) to implement the test files and execute them.
- Dispatch Reviewers and Challengers to verify completeness and robustness.
- Dispatch Forensic Auditor to verify no mock bypasses or cheating.
- Once all pass and TEST_READY.md is published, send your completion report via send_message to parent (0d3371b1-47b5-4496-8d28-86e91a40d7fc).
