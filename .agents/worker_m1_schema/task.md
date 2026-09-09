# Task: Milestone 1 Worker Implementation

## Objective
Implement Milestone 1 deliverables:
1. Update `scripts/girls_hostel_schema.sql`:
   - Dedicated `girls_hostel` schema.
   - Tables: `student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings`.
   - ENABLE ROW LEVEL SECURITY on all 4 tables with appropriate policies for service_role.
   - HNSW vector index: `idx_girls_hostel_students_embedding ON girls_hostel.student_profiles USING hnsw (embedding vector_cosine_ops)`.
   - RPC function `girls_hostel.match_face(query_embedding VECTOR(512), match_threshold FLOAT DEFAULT 0.40, match_count INT DEFAULT 1)` returning id, name, roll_number, room_number, current_status, similarity.
   - Default settings insertion into `girls_hostel.system_settings`.
2. Implement / Refactor `src/utils/hostel_db.py`:
   - Complete database abstraction strictly targeting `girls_hostel.*`.
   - Strict architectural constraint: ZERO references, reads, writes, or queries to `public.student_profiles` or `public.attendance_logs` or any `public` tables.
   - CRUD functions for student profiles, movement logs, curfew alerts, system settings, and vector matching.
   - Graceful connection handling (Supabase client or connection pool with mock/fallback for test mode).
3. Comprehensive Unit Tests in `tests/unit/test_m1_schema_db.py`:
   - Validates SQL DDL syntax, RLS enabled on all tables, HNSW index syntax, RPC signature.
   - Validates zero occurrences of `public.` in all hostel database files.
   - Validates all hostel_db utility functions.
4. Execute tests via pytest in `.venv` or system python and verify all pass.
5. Provide handoff report in `.agents/worker_m1_schema/handoff.md`.
