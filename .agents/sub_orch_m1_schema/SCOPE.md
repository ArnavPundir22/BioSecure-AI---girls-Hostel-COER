# Scope: Milestone 1 — Isolated PostgreSQL Schema & Database Layer

## Architecture & Isolation Rules
- Dedicated schema: `girls_hostel` strictly separated from default `public` schema.
- Zero references, imports, reads, writes, or queries to `public.student_profiles` or `public.attendance_logs` or any other `public` tables.
- All tables, indexes, RPC functions, and queries reside within `girls_hostel`.

## Schema Specification (`scripts/girls_hostel_schema.sql`)
1. **Schema**:
   - `CREATE SCHEMA IF NOT EXISTS girls_hostel;`
2. **Tables**:
   - `girls_hostel.student_profiles`:
     - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `name VARCHAR(255) NOT NULL`
     - `roll_number VARCHAR(100) UNIQUE NOT NULL`
     - `room_number VARCHAR(50) NOT NULL`
     - `hostel_block VARCHAR(50) DEFAULT 'Block-A'`
     - `parent_contact VARCHAR(20) NOT NULL`
     - `student_contact VARCHAR(20)`
     - `embedding VECTOR(512)`
     - `current_status VARCHAR(20) DEFAULT 'IN'`
     - `last_movement_time TIMESTAMP WITH TIME ZONE`
     - `current_ewma_drift FLOAT DEFAULT 0.0`
     - `drift_alert_level VARCHAR(50) DEFAULT 'HEALTHY'`
     - `created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
   - `girls_hostel.movement_logs`:
     - `id BIGSERIAL PRIMARY KEY`
     - `student_id UUID NOT NULL REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE`
     - `direction VARCHAR(10) NOT NULL` ('IN' / 'OUT')
     - `camera_id VARCHAR(50) NOT NULL` ('CAM_01_ENTRY' / 'CAM_02_EXIT')
     - `timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
     - `confidence FLOAT DEFAULT 1.0`
     - `snapshot_url TEXT`
   - `girls_hostel.curfew_alerts`:
     - `id BIGSERIAL PRIMARY KEY`
     - `student_id UUID NOT NULL REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE`
     - `curfew_date DATE DEFAULT CURRENT_DATE`
     - `system_start_time TIME DEFAULT '17:00:00'`
     - `curfew_end_time TIME DEFAULT '19:30:00'`
     - `status VARCHAR(30) DEFAULT 'OVERDUE_OUT'`
     - `alert_triggered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
     - `resolved_at TIMESTAMP WITH TIME ZONE`
     - `notes TEXT`
   - `girls_hostel.system_settings`:
     - `key VARCHAR(100) PRIMARY KEY`
     - `value JSONB NOT NULL`
     - `updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
3. **Row Level Security (RLS)**:
   - `ALTER TABLE girls_hostel.student_profiles ENABLE ROW LEVEL SECURITY;`
   - `ALTER TABLE girls_hostel.movement_logs ENABLE ROW LEVEL SECURITY;`
   - `ALTER TABLE girls_hostel.curfew_alerts ENABLE ROW LEVEL SECURITY;`
   - `ALTER TABLE girls_hostel.system_settings ENABLE ROW LEVEL SECURITY;`
   - Policies defined for `service_role` (full access).
4. **Vector Index**:
   - `CREATE INDEX IF NOT EXISTS idx_girls_hostel_students_embedding ON girls_hostel.student_profiles USING hnsw (embedding vector_cosine_ops);`
5. **RPC Function**:
   - `girls_hostel.match_face(query_embedding VECTOR(512), match_threshold FLOAT DEFAULT 0.40, match_count INT DEFAULT 1)`
   - Returns table: `(id UUID, name VARCHAR(255), roll_number VARCHAR(100), room_number VARCHAR(50), current_status VARCHAR(20), similarity FLOAT)`
   - Defined with `SECURITY DEFINER` and calculation `1 - (sp.embedding <=> query_embedding)`.
6. **Default Configuration Insert**:
   - Curfew schedule: 17:00 to 19:30, enabled: true.
   - Camera sources: entry_cam: "0", exit_cam: "1".
   - Alert config: smtp_enabled: true, cooldown_seconds: 15.

## Interface Contract (`src/utils/hostel_db.py`)
- Strictly targets `HOSTEL_SCHEMA = "girls_hostel"`.
- Must provide:
  - `get_student_by_id(student_id: str) -> Optional[dict]`
  - `fetch_all_hostel_students() -> list[dict]`
  - `match_face_embedding(embedding: list[float], threshold: float = 0.40, count: int = 1) -> list[dict]`
  - `match_hostel_face(query_embedding: list[float], threshold: float = 0.40) -> list[dict]` (compat)
  - `update_student_status(student_id: str, status: str, movement_time: Optional[datetime] = None) -> bool`
  - `update_student_movement_state(student_id: str, direction: str, camera_id: str) -> bool` (compat)
  - `insert_movement_log(student_id: str, direction: str, camera_id: str, confidence: float = 1.0, snapshot_url: Optional[str] = None) -> Optional[int]`
  - `get_recent_movement_logs(limit: int = 50) -> list[dict]`
  - `fetch_recent_movement_logs(limit: int = 50) -> list[dict]` (compat)
  - `get_active_curfew_alerts() -> list[dict]`
  - `fetch_overdue_curfew_students() -> list[dict]` (compat)
  - `create_curfew_alert(student_id: str, curfew_date: Optional[date] = None, start_time: str = '17:00:00', end_time: str = '19:30:00', status: str = 'OVERDUE_OUT') -> Optional[int]`
  - `resolve_curfew_alert(alert_id: int, status: str = 'RESOLVED', notes: str = '') -> bool`
  - `get_system_settings(key: str) -> Optional[dict]`
  - `update_system_settings(key: str, value: dict) -> bool`
- Graceful connection handling:
  - Supports mock/fallback or decoupled client injection for offline/unit test execution.
  - Zero crashes when offline or when external Supabase URL cannot be contacted during tests.

## Test Requirements (`tests/unit/test_m1_schema_db.py`)
- DDL syntax validation: parses SQL script, verifies schema name `girls_hostel`, all 4 tables, RLS statements for all 4 tables, HNSW index syntax, and RPC function definition.
- Zero public schema leakage test: ensures no occurrences of `public.` in SQL DDL and `src/utils/hostel_db.py`.
- Unit tests for all `hostel_db.py` functions with mock client or fixture.
- Edge cases: invalid student ID, empty embeddings, missing settings, duplicate alerts.
