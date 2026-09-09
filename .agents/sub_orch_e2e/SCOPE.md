# Scope: E2E Testing Suite for BioSecure AI - Girls Hostel Security System

## Architecture
- Independent, opaque-box E2E testing harness utilizing `pytest`.
- Test suite located at `tests/e2e/`.
- Validates all 5 Core Requirements (R1-R5) under isolated conditions.
- Test runner and environment configuration with mocked camera/network inputs or direct service/database verification where appropriate, verifying real logic and zero leaks.

## Test Tiers Decomposition
| Tier | Description | Minimum Tests | Focus Areas |
|------|-------------|--------------:|-------------|
| Tier 1 | Feature Coverage | 25 (5/feature) | R1: Schema isolation, RLS, match_face RPC, zero public.* leaks<br>R2: Dual camera simultaneous ingestion, multi-face (up to 10), <200ms batch<br>R3: Movement state machine: CAM_02 Exit->OUT, CAM_01 Entry->IN, 15s cooldown<br>R4: Curfew schedule (17:00-19:30), overdue scanning, OVERDUE_OUT alert, parent contacts<br>R5: Warden dashboard endpoints (/hostel, streams, APIs, stats, resolve) |
| Tier 2 | Boundary & Corner Cases | 25 (5/feature) | 14.9s vs 15.1s cooldown boundary; 19:29:59 vs 19:30:01 curfew boundary; rapid repeated faces, extreme face sizes/orientations; missing parent contacts/malformed payloads; alert idempotency |
| Tier 3 | Cross-Feature Combinations | 8 | Entry -> Cooldown -> Curfew transitions; Match -> State change -> Alert resolution -> Exit; Concurrent multi-gate detections |
| Tier 4 | Real-World Scenarios | 5 | Evening mass exit before curfew, late return after curfew trigger; Multi-student overdue alert batch dispatch with warden dashboard verification |
| **Total** | | **≥63** | Comprehensive opaque-box verification |

## Interface Contracts Under Test
- Database: `girls_hostel.*` strictly isolated, zero reads/writes to `public.*`
- Detection & Ingestion: dual camera ingestion handling up to 10 faces simultaneously
- State Engine: `process_student_detection` with 15-second debounce cooldown
- Curfew Scanner: `check_curfew_violations` flagging overdue OUT students past 19:30
- Web APIs: Flask routes `/hostel`, `/hostel/api/stats`, `/hostel/api/movement_logs`, `/hostel/api/overdue_alerts`, `/hostel/api/resolve_alert`
