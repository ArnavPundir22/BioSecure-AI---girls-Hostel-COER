## 2026-09-09T04:59:28Z
You are worker_m1_schema, the implementation worker for Milestone 1 of BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Working Directory: /home/dell/BioSecure AI - GIrls Hostel/.agents/worker_m1_schema
Workspace Root: /home/dell/BioSecure AI - GIrls Hostel
Project Specification: /home/dell/BioSecure AI - GIrls Hostel/.agents/sub_orch_m1_schema/SCOPE.md
Parent Sub-Orchestrator Conversation ID: 77d53b6c-179f-4673-b017-12adecd865be

Your Assigned Deliverables:
1. Update `scripts/girls_hostel_schema.sql`:
   - Ensure the dedicated `girls_hostel` schema is created if not exists.
   - Tables: `student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings`.
   - ENABLE ROW LEVEL SECURITY on ALL 4 tables:
     ALTER TABLE girls_hostel.student_profiles ENABLE ROW LEVEL SECURITY;
     ALTER TABLE girls_hostel.movement_logs ENABLE ROW LEVEL SECURITY;
     ALTER TABLE girls_hostel.curfew_alerts ENABLE ROW LEVEL SECURITY;
     ALTER TABLE girls_hostel.system_settings ENABLE ROW LEVEL SECURITY;
   - Add appropriate RLS policies for `service_role` (and security definer functions).
   - HNSW vector index: `idx_girls_hostel_students_embedding ON girls_hostel.student_profiles USING hnsw (embedding vector_cosine_ops);`
   - RPC function `girls_hostel.match_face(query_embedding VECTOR(512), match_threshold FLOAT DEFAULT 0.40, match_count INT DEFAULT 1)` returning `TABLE (id UUID, name VARCHAR(255), roll_number VARCHAR(100), room_number VARCHAR(50), current_status VARCHAR(20), similarity FLOAT)` with `SECURITY DEFINER` and calculation `1 - (sp.embedding <=> query_embedding)`.
   - Insert default settings into `girls_hostel.system_settings` for curfew_schedule, camera_sources, and alert_config.
   - Grants to `service_role` on schema, tables, functions, sequences.

2. Implement / Refactor `src/utils/hostel_db.py`:
   - Complete database abstraction strictly targeting `girls_hostel.*`.
   - Strict architectural constraint: ZERO references, reads, writes, or queries to `public.student_profiles` or `public.attendance_logs` or any `public` tables.
   - Provide all required interface methods:
     - `get_student_by_id(student_id: str) -> Optional[dict]`
     - `fetch_all_hostel_students() -> list[dict]`
     - `match_face_embedding(embedding: list[float], threshold: float = 0.40, count: int = 1) -> list[dict]`
     - `match_hostel_face(query_embedding: list[float], threshold: float = 0.40) -> list[dict]`
     - `update_student_status(student_id: str, status: str, movement_time: Optional[datetime] = None) -> bool`
     - `update_student_movement_state(student_id: str, direction: str, camera_id: str) -> bool`
     - `insert_movement_log(student_id: str, direction: str, camera_id: str, confidence: float = 1.0, snapshot_url: Optional[str] = None) -> Optional[int]`
     - `get_recent_movement_logs(limit: int = 50) -> list[dict]`
     - `fetch_recent_movement_logs(limit: int = 50) -> list[dict]`
     - `get_active_curfew_alerts() -> list[dict]`
     - `fetch_overdue_curfew_students() -> list[dict]`
     - `create_curfew_alert(student_id: str, curfew_date: Optional[date] = None, start_time: str = '17:00:00', end_time: str = '19:30:00', status: str = 'OVERDUE_OUT') -> Optional[int]`
     - `resolve_curfew_alert(alert_id: int, status: str = 'RESOLVED', notes: str = '') -> bool`
     - `get_system_settings(key: str) -> Optional[dict]`
     - `update_system_settings(key: str, value: dict) -> bool`
   - Graceful connection handling:
     - Ensure fallback/mock mechanism or safe client initialization so tests and offline runs do not crash if live Supabase network endpoint is unreachable. You can support an optional mock client parameter, environment variable check, or mock adapter when executing in test environments.

3. Create Comprehensive Unit Tests in `tests/unit/test_m1_schema_db.py`:
   - Test 1: SQL DDL syntax and completeness validation:
     - Verifies `girls_hostel` schema definition.
     - Verifies creation of all 4 tables (`student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings`).
     - Verifies `ENABLE ROW LEVEL SECURITY` on each of the 4 tables.
     - Verifies `CREATE POLICY` statements for the tables.
     - Verifies `idx_girls_hostel_students_embedding` with `USING hnsw` and `vector_cosine_ops`.
     - Verifies `girls_hostel.match_face` RPC signature and parameters.
   - Test 2: Schema Isolation & Zero-Leakage:
     - Scans `scripts/girls_hostel_schema.sql` and `src/utils/hostel_db.py` to ensure ZERO occurrences of `public.` or references to `public.student_profiles` or `public.attendance_logs`.
   - Test 3: Functional Unit Tests for `hostel_db.py`:
     - Test all interface functions using mock client fixtures / test mode.
     - Test edge cases: student not found, empty results, setting updates, alert resolution, etc.

4. Run the tests using pytest:
   - Run `pytest tests/unit/test_m1_schema_db.py -v` (or `./.venv/bin/pytest tests/unit/test_m1_schema_db.py -v`).
   - Ensure 100% of tests pass.

5. Update your progress in `.agents/worker_m1_schema/progress.md` and write your completion report in `.agents/worker_m1_schema/handoff.md`.
6. Send a message to the caller (`77d53b6c-179f-4673-b017-12adecd865be`) summarizing what was implemented, the test commands executed, and the test results.
