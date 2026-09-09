-- ============================================================================
-- BIOSECURE AI — GIRLS HOSTEL ISOLATED SCHEMA MIGRATION SCRIPT
-- ============================================================================
-- Executing this script creates the dedicated 'girls_hostel' schema and all
-- required isolated tables, indexes, and RPC functions.
-- It ensures 100% isolation from classroom attendance data.

-- 1. Enable Vector Extension & Create Isolated Schema
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS girls_hostel;

-- 2. Create Student Profiles Table (girls_hostel.student_profiles)
CREATE TABLE IF NOT EXISTS girls_hostel.student_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    roll_number VARCHAR(100) UNIQUE NOT NULL,
    room_number VARCHAR(50) NOT NULL,
    hostel_block VARCHAR(50) DEFAULT 'Block-A',
    parent_contact VARCHAR(20) NOT NULL,
    student_contact VARCHAR(20),
    embedding VECTOR(512),                           -- ArcFace 512D Vector
    current_status VARCHAR(20) DEFAULT 'IN',          -- 'IN' (Inside) or 'OUT' (Outside)
    last_movement_time TIMESTAMP WITH TIME ZONE,
    current_ewma_drift FLOAT DEFAULT 0.0,            -- Patent EWMA drift tracking
    drift_alert_level VARCHAR(50) DEFAULT 'HEALTHY',  -- HEALTHY / WARNING / CRITICAL / ALERT
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- HNSW Vector Index on girls_hostel.student_profiles
CREATE INDEX IF NOT EXISTS idx_girls_hostel_students_embedding
ON girls_hostel.student_profiles 
USING hnsw (embedding vector_cosine_ops);

-- 3. Create Movement Logs Table (girls_hostel.movement_logs)
CREATE TABLE IF NOT EXISTS girls_hostel.movement_logs (
    id BIGSERIAL PRIMARY KEY,
    student_id UUID NOT NULL REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE,
    direction VARCHAR(10) NOT NULL,                  -- 'IN' or 'OUT'
    camera_id VARCHAR(50) NOT NULL,                   -- 'CAM_01_ENTRY' or 'CAM_02_EXIT'
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    confidence FLOAT DEFAULT 1.0,
    snapshot_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_girls_hostel_movement_student_time 
ON girls_hostel.movement_logs (student_id, timestamp DESC);

-- 4. Create Curfew Alerts Table (girls_hostel.curfew_alerts)
CREATE TABLE IF NOT EXISTS girls_hostel.curfew_alerts (
    id BIGSERIAL PRIMARY KEY,
    student_id UUID NOT NULL REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE,
    curfew_date DATE DEFAULT CURRENT_DATE,
    system_start_time TIME DEFAULT '17:00:00',
    curfew_end_time TIME DEFAULT '19:30:00',
    status VARCHAR(30) DEFAULT 'OVERDUE_OUT',         -- 'OVERDUE_OUT', 'RESOLVED', 'EXCUSED'
    alert_triggered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_girls_hostel_curfew_status 
ON girls_hostel.curfew_alerts (status, curfew_date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_girls_hostel_curfew_active_uniq 
ON girls_hostel.curfew_alerts (student_id, curfew_date) 
WHERE status = 'OVERDUE_OUT';

-- 5. Create System Configuration Table (girls_hostel.system_settings)
CREATE TABLE IF NOT EXISTS girls_hostel.system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert Default System Settings
INSERT INTO girls_hostel.system_settings (key, value) VALUES
('curfew_schedule', '{"start_time": "17:00", "end_time": "19:30", "enabled": true}'),
('camera_sources', '{"entry_cam": "0", "exit_cam": "1"}'),
('alert_config', '{"smtp_enabled": true, "cooldown_seconds": 15}')
ON CONFLICT (key) DO NOTHING;

-- 6. Enable Row Level Security (RLS) on all 4 tables
ALTER TABLE girls_hostel.student_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE girls_hostel.movement_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE girls_hostel.curfew_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE girls_hostel.system_settings ENABLE ROW LEVEL SECURITY;

-- Service Role Full Access Policies
DROP POLICY IF EXISTS service_role_all_student_profiles ON girls_hostel.student_profiles;
CREATE POLICY service_role_all_student_profiles ON girls_hostel.student_profiles
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_all_movement_logs ON girls_hostel.movement_logs;
CREATE POLICY service_role_all_movement_logs ON girls_hostel.movement_logs
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_all_curfew_alerts ON girls_hostel.curfew_alerts;
CREATE POLICY service_role_all_curfew_alerts ON girls_hostel.curfew_alerts
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_all_system_settings ON girls_hostel.system_settings;
CREATE POLICY service_role_all_system_settings ON girls_hostel.system_settings
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 7. Isolated Vector Matching RPC Function (girls_hostel.match_face)
CREATE OR REPLACE FUNCTION girls_hostel.match_face(
    query_embedding VECTOR(512),
    match_threshold FLOAT DEFAULT 0.40,
    match_count INT DEFAULT 1
)
RETURNS TABLE (
    id UUID,
    name VARCHAR(255),
    roll_number VARCHAR(100),
    room_number VARCHAR(50),
    current_status VARCHAR(20),
    similarity FLOAT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = girls_hostel, pg_temp
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        sp.id, 
        sp.name, 
        sp.roll_number, 
        sp.room_number,
        sp.current_status,
        1 - (sp.embedding <=> query_embedding) AS similarity
    FROM girls_hostel.student_profiles sp
    WHERE sp.embedding IS NOT NULL
      AND 1 - (sp.embedding <=> query_embedding) >= match_threshold
    ORDER BY sp.embedding <=> query_embedding ASC
    LIMIT match_count;
END;
$$;

-- 8. Grant Permissions to Service Role
GRANT ALL ON SCHEMA girls_hostel TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA girls_hostel TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA girls_hostel TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA girls_hostel TO service_role;
