# Original User Request — Sub-Orchestrator M1 Schema

## 2026-09-09T04:57:56Z

You are the Milestone 1 (M1) Sub-Orchestrator for the BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System project.

Parent Conversation ID: 0d3371b1-47b5-4496-8d28-86e91a40d7fc
Workspace root: /home/dell/BioSecure AI - GIrls Hostel
Your working directory: /home/dell/BioSecure AI - GIrls Hostel/.agents/sub_orch_m1_schema
Reference files:
- /home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md
- /home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator/PROJECT.md

Scope:
Milestone 1 — Isolated PostgreSQL Schema Migration (`girls_hostel`) & Database Layer.

Key Deliverables:
1. Update `scripts/girls_hostel_schema.sql`:
   - Dedicated `girls_hostel` schema.
   - Tables: `student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings`.
   - ENABLE ROW LEVEL SECURITY on all 4 tables with appropriate policies for service_role and security definer functions.
   - HNSW vector index on 512D ArcFace embeddings: `idx_girls_hostel_students_embedding ON girls_hostel.student_profiles USING hnsw (embedding vector_cosine_ops)`.
   - RPC function `girls_hostel.match_face(query_embedding VECTOR(512), match_threshold FLOAT DEFAULT 0.40, match_count INT DEFAULT 1)` returning id, name, roll_number, room_number, current_status, similarity.
   - Default settings insertion into `girls_hostel.system_settings`.
2. Implement / Refactor `src/utils/hostel_db.py`:
   - Complete database abstraction strictly targeting `girls_hostel.*`.
   - Strict architectural constraint: ZERO references, reads, writes, or queries to `public.student_profiles` or `public.attendance_logs`.
   - CRUD functions for student profiles, movement logs, curfew alerts, system settings, and vector matching.
   - Graceful connection handling (Supabase client or connection pool with mock/fallback for test mode).
3. Comprehensive Unit Tests in `tests/unit/test_m1_schema_db.py`:
   - Validates SQL DDL syntax, RLS enabled on all tables, HNSW index syntax, RPC signature.
   - Validates zero occurrences of `public.` in all hostel database files.
   - Validates all hostel_db utility functions.
4. Orchestration Loop:
   - Initialize BRIEFING.md and progress.md in your working directory.
   - Spawn Worker (`teamwork_preview_worker`) with mandatory integrity warning to implement changes and run tests.
   - Spawn Reviewer (`teamwork_preview_reviewer`) to verify interface conformance and schema isolation.
   - Spawn Challenger (`teamwork_preview_challenger`) to stress-test schema boundaries and data isolation.
   - Spawn Forensic Auditor (`teamwork_preview_auditor`) to audit against schema leakage or hardcoded dummy results.
   - Evaluate gate and report completion via send_message to parent (0d3371b1-47b5-4496-8d28-86e91a40d7fc).
