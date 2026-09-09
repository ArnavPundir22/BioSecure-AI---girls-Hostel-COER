## 2026-09-09T05:10:57Z
You are worker_m1_fix, the remediation worker for Milestone 1.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Working Directory: /home/dell/BioSecure AI - GIrls Hostel/.agents/worker_m1_fix
Task Specification: /home/dell/BioSecure AI - GIrls Hostel/.agents/worker_m1_fix/task.md
Parent Sub-Orchestrator Conversation ID: 77d53b6c-179f-4673-b017-12adecd865be

Your mission:
Implement the 3 major hardening fixes identified during code review:
1. `scripts/girls_hostel_schema.sql`:
   - Add `SET search_path = girls_hostel, pg_temp;` to `girls_hostel.match_face` RPC definition right above `AS $$`.
   - Add partial unique index for active alert deduplication:
     `CREATE UNIQUE INDEX IF NOT EXISTS idx_girls_hostel_curfew_active_uniq ON girls_hostel.curfew_alerts (student_id, curfew_date) WHERE status = 'OVERDUE_OUT';`
2. `src/utils/hostel_db.py`:
   - In `get_hostel_client`: Never return an unscoped live client that could point to `public`. If `client.schema(HOSTEL_SCHEMA)` fails, return `_mock_client_instance` with warning or raise an exception; NEVER fall back to returning the unscoped client.
   - In `create_curfew_alert`: Check if active alert with status 'OVERDUE_OUT' already exists for that student and date. If so, return existing alert ID to prevent duplicates.
   - In `update_student_movement_state`: Check `if not status_ok: return False` before calling `insert_movement_log`.
   - Update `MockHostelSupabaseClient` to support active alert deduplication if relevant.
3. `tests/unit/test_m1_schema_db.py`:
   - Add tests for `SET search_path = girls_hostel, pg_temp;` and `idx_girls_hostel_curfew_active_uniq` in DDL tests.
   - Add unit tests for duplicate active alert prevention in `create_curfew_alert`.
   - Add unit test for `update_student_movement_state` short-circuiting on non-existent student.
   - Add unit test verifying `get_hostel_client` isolation.
4. Run `./.venv/bin/pytest tests/unit/test_m1_schema_db.py -v` and `./.venv/bin/flake8 src/utils/hostel_db.py tests/unit/test_m1_schema_db.py`.
5. Write your handoff report to `.agents/worker_m1_fix/handoff.md` and send a message back to parent `77d53b6c-179f-4673-b017-12adecd865be`.
