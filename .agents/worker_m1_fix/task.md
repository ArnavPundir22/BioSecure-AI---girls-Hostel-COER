# Task: Worker M1 Fix — Implement Reviewer Hardening Items

## Objectives
Fix the specific findings identified by Reviewer 1 & Reviewer 2:

1. In `scripts/girls_hostel_schema.sql`:
   - Add `SET search_path = girls_hostel, pg_temp;` to `girls_hostel.match_face` RPC function definition above `AS $$`.
   - Add partial unique index to prevent duplicate active alerts for the same student on the same day:
     `CREATE UNIQUE INDEX IF NOT EXISTS idx_girls_hostel_curfew_active_uniq ON girls_hostel.curfew_alerts (student_id, curfew_date) WHERE status = 'OVERDUE_OUT';`

2. In `src/utils/hostel_db.py`:
   - In `get_hostel_client(client)`: Never return an unscoped live client. If `client.schema(HOSTEL_SCHEMA)` fails on a client, do NOT return the unscoped client (which would default to `public`). Instead, log a warning and return `_mock_client_instance` or raise an isolation exception.
   - In `create_curfew_alert(...)`: Add deduplication check: if an active alert (`status = 'OVERDUE_OUT'`) already exists for `(student_id, curfew_date)`, return the existing alert ID instead of inserting a duplicate.
   - In `update_student_movement_state(...)`: Short-circuit `if not status_ok: return False` before calling `insert_movement_log` to prevent orphaned movement logs for non-existent students.
   - In `MockHostelSupabaseClient`: support the unique constraint / deduplication on `(student_id, curfew_date)` for active alerts.

3. In `tests/unit/test_m1_schema_db.py`:
   - Add test for `SET search_path` in `girls_hostel.match_face` RPC.
   - Add test for `idx_girls_hostel_curfew_active_uniq` in schema DDL tests.
   - Add functional test for duplicate curfew alert handling in `create_curfew_alert`.
   - Add functional test for `update_student_movement_state` short-circuiting on invalid student ID.
   - Add test verifying that `get_hostel_client` never returns an unscoped public client.

4. Run `./.venv/bin/pytest tests/unit/test_m1_schema_db.py -v` and `./.venv/bin/flake8 src/utils/hostel_db.py tests/unit/test_m1_schema_db.py`.
5. Update progress and provide handoff in `.agents/worker_m1_fix/handoff.md`.
