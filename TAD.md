# ⚙️ Technical Architecture Document (TAD) — BioSecure AI: Girls Hostel System

## 1. Technology Stack & Dependencies

| Component | Framework / Library | Version / Details | Purpose |
|---|---|---|---|
| **Programming Language** | Python | `3.10+` | Core application framework & ML pipeline execution. |
| **Web Server / Framework** | Flask / WSGI (Gunicorn) | Flask `3.1.x`, Gunicorn `21.x` | REST APIs, live stream streaming, dashboard rendering. |
| **Biometric ML Engine** | InsightFace | `buffalo_l` (ArcFace + RetinaFace) | 512D face detection, landmark alignment, vector extraction. |
| **Database & Vector Engine**| Supabase PostgreSQL | PostgreSQL 15+ with `pgvector` | Isolated database storage in `girls_hostel` schema. |
| **Vector Indexing** | HNSW (Hierarchical Navigable Small World) | `vector_cosine_ops` | Sub-millisecond similarity matching in PostgreSQL. |
| **Video Ingestion** | OpenCV / WebRTC | `opencv-python-headless 4.10+` | Camera stream acquisition (RTSP/USB/HTTP). |
| **Styling & UI** | TailwindCSS + HTML5 Canvas | Dark Glassmorphic Theme | Warden Dashboard & multi-camera feed overlay. |

---

## 2. Complete SQL Schema Definition (`girls_hostel`)

```sql
-- ============================================================================
-- BIOSECURE AI — GIRLS HOSTEL ISOLATED SCHEMA MIGRATION
-- ============================================================================

-- 1. Create Schema
CREATE SCHEMA IF NOT EXISTS girls_hostel;

-- 2. Student Profiles Table (Isolated from public)
CREATE TABLE girls_hostel.student_profiles (
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

-- HNSW Vector Index under girls_hostel schema
CREATE INDEX IF NOT EXISTS idx_girls_hostel_students_embedding
ON girls_hostel.student_profiles 
USING hnsw (embedding vector_cosine_ops);

-- 3. Movement Logs Table
CREATE TABLE girls_hostel.movement_logs (
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

-- 4. Curfew Overdue Alerts Table
CREATE TABLE girls_hostel.curfew_alerts (
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

-- 5. System Configuration Table
CREATE TABLE girls_hostel.system_settings (
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

-- 6. Isolated Vector Matching RPC Function
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
```

---

## 3. Movement State Machine & Cooldown Algorithm

```python
# Pseudo-code / Core Logic for Movement & Anti-Bounce Cooldown
from datetime import datetime, timezone
import logging

COOLDOWN_SECONDS = 15
student_cooldown_map = {}  # {student_id: (last_camera_id, last_timestamp)}

def process_detected_student(student_id: str, camera_id: str, db_client):
    now = datetime.now(timezone.utc)
    
    # 1. Anti-bounce cooldown check
    if student_id in student_cooldown_map:
        last_cam, last_time = student_cooldown_map[student_id]
        if last_cam == camera_id and (now - last_time).total_seconds() < COOLDOWN_SECONDS:
            logging.info(f"Cooldown active for student {student_id} on {camera_id}. Skipping.")
            return None
            
    # 2. Fetch current status from girls_hostel schema
    res = db_client.schema("girls_hostel").table("student_profiles").select("current_status").eq("id", student_id).single().execute()
    current_status = res.data.get("current_status", "IN")
    
    # 3. Determine new direction & state transition
    target_direction = "OUT" if camera_id == "CAM_02_EXIT" else "IN"
    
    # State update logic
    db_client.schema("girls_hostel").table("student_profiles").update({
        "current_status": target_direction,
        "last_movement_time": now.isoformat()
    }).eq("id", student_id).execute()
    
    # Insert isolated movement log
    db_client.schema("girls_hostel").table("movement_logs").insert({
        "student_id": student_id,
        "direction": target_direction,
        "camera_id": camera_id,
        "timestamp": now.isoformat()
    }).execute()
    
    # Update cooldown map
    student_cooldown_map[student_id] = (camera_id, now)
    return target_direction
```

---

## 4. Curfew Overdue Alert Algorithm

```python
# Pseudo-code for Curfew Alert Scanner (Runs every 60 seconds)
def scan_curfew_overdue_students(db_client):
    now = datetime.now()
    curfew_end = now.replace(hour=19, minute=30, second=0, microsecond=0)
    
    if now >= curfew_end:
        # Query students who are currently OUT in girls_hostel schema
        res = db_client.schema("girls_hostel").table("student_profiles") \
            .select("id, name, roll_number, room_number, parent_contact, last_movement_time") \
            .eq("current_status", "OUT").execute()
            
        overdue_students = res.data
        for student in overdue_students:
            # Check if alert already logged for today
            alert_check = db_client.schema("girls_hostel").table("curfew_alerts") \
                .select("id").eq("student_id", student["id"]) \
                .eq("curfew_date", now.date().isoformat()) \
                .eq("status", "OVERDUE_OUT").execute()
                
            if not alert_check.data:
                # Log new overdue alert
                db_client.schema("girls_hostel").table("curfew_alerts").insert({
                    "student_id": student["id"],
                    "curfew_date": now.date().isoformat(),
                    "system_start_time": "17:00:00",
                    "curfew_end_time": "19:30:00",
                    "status": "OVERDUE_OUT"
                }).execute()
                
                # Trigger Email / Dashboard Notification
                send_overdue_alert_notification(student)
```
