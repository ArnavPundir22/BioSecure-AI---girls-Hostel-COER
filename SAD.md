# 🏛️ System Architecture Document (SAD) — BioSecure AI: Girls Hostel System

## 1. Architectural Principles & Vision
The architecture of **BioSecure AI - Girls Hostel Edition** is built around three core pillars:
1. **Isolated Data Domain**: The entire data model is encapsulated inside a dedicated `girls_hostel` PostgreSQL schema. This ensures zero data leakage, zero shared sequence collision, and zero operational impact on other projects (such as academic classroom attendance).
2. **Real-Time Dual Stream Computer Vision Pipeline**: Multithreaded frame acquisition from two distinct cameras (`CAM_01_ENTRY` and `CAM_02_EXIT`) feeding a parallel InsightFace vector extraction engine.
3. **Automated Event-Driven Curfew Engine**: Continuous time-aware monitoring that checks student state (`IN`/`OUT`) against configurable curfew bounds (5:00 PM - 7:30 PM) and publishes real-time overdue alerts.

---

## 2. High-Level System Topology

```mermaid
flowchart TB
    subgraph Edge_Cameras["Edge Video Sources"]
        C1["Camera 1: ENTRY (Returning Students)"]
        C2["Camera 2: EXIT (Outside-Going Students)"]
    end

    subgraph Application_Server["Flask Application Backend (Python 3.10+)"]
        INGEST["Stream Ingestion Manager (OpenCV / RTSP)"]
        DETECTOR["InsightFace RetinaFace + ArcFace 512D"]
        FSM_ENGINE["State Machine & Anti-Bounce Cooldown"]
        CURFEW_SVC["Curfew Monitoring Service (Cron Worker)"]
        API_LAYER["Flask REST & Event Blueprint (/hostel/*)"]
    end

    subgraph Supabase_PostgreSQL["Supabase PostgreSQL Cloud"]
        subgraph Public_Schema["public schema (Classroom Attendance)"]
            PUB_STUDENTS["public.student_profiles"]
            PUB_ATTENDANCE["public.attendance_logs"]
        end

        subgraph Isolated_Hostel_Schema["girls_hostel schema (HOSTEL ISOLATED)"]
            HOSTEL_STUDENTS["girls_hostel.student_profiles"]
            HOSTEL_LOGS["girls_hostel.movement_logs"]
            HOSTEL_ALERTS["girls_hostel.curfew_alerts"]
            HOSTEL_SETTINGS["girls_hostel.system_settings"]
            HOSTEL_RPC["girls_hostel.match_face() RPC"]
        end
    end

    subgraph Presentation_Clients["Warden & Security Interfaces"]
        WARDEN_UI["Hostel Warden Dashboard"]
        SECURITY_UI["Gate Security Live Stream Monitor"]
        EMAIL_ALERT["SMTP Email / Alert Notifications"]
    end

    C1 -->|RTSP / WebRTC| INGEST
    C2 -->|RTSP / WebRTC| INGEST
    INGEST --> DETECTOR
    DETECTOR --> FSM_ENGINE
    FSM_ENGINE -->|RPC Query| HOSTEL_RPC
    HOSTEL_RPC --> HOSTEL_STUDENTS
    FSM_ENGINE -->|Insert Movement Log| HOSTEL_LOGS
    CURFEW_SVC -->|Scan Overdue OUT Students| HOSTEL_STUDENTS
    CURFEW_SVC -->|Write Alerts| HOSTEL_ALERTS
    
    API_LAYER --> WARDEN_UI
    API_LAYER --> SECURITY_UI
    CURFEW_SVC --> EMAIL_ALERT
```

---

## 3. Data Isolation Architecture & Boundary Control

### 3.1 Database Schema Isolation Strategy
To guarantee complete independence from other projects:
- **Dedicated Schema**: All tables are created under `girls_hostel.*`.
- **Dedicated Functions**: Vector search RPC function is registered as `girls_hostel.match_face()`.
- **Index Isolation**: HNSW cosine distance index is created on `girls_hostel.student_profiles(embedding vector_cosine_ops)`.
- **Application Connection Scoping**: Supabase backend clients execute schema-scoped SQL queries, preventing accidental table hits in `public`.

```sql
-- Schema Creation
CREATE SCHEMA IF NOT EXISTS girls_hostel;

-- Table Scoping Example
CREATE TABLE girls_hostel.student_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    roll_number VARCHAR(100) UNIQUE NOT NULL,
    room_number VARCHAR(50) NOT NULL,
    hostel_block VARCHAR(50) DEFAULT 'Block-A',
    parent_contact VARCHAR(20) NOT NULL,
    embedding VECTOR(512),
    current_status VARCHAR(20) DEFAULT 'IN', -- 'IN' or 'OUT'
    last_movement_time TIMESTAMP WITH TIME ZONE,
    current_ewma_drift FLOAT DEFAULT 0.0,
    drift_alert_level VARCHAR(50) DEFAULT 'HEALTHY',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Multi-Face Camera Ingestion Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant Cam as Camera 01 (Entry) / Camera 02 (Exit)
    participant Worker as Video Stream Worker
    participant AI as InsightFace Engine
    participant Cache as In-Memory Vector Cache
    participant DB as Supabase (girls_hostel)
    participant FSM as Movement State Machine

    Cam->>Worker: Live Video Frame Batch
    Worker->>AI: Detect Faces (RetinaFace)
    AI-->>Worker: Bounding Boxes + Landmarks (N faces)
    
    loop For each detected face
        Worker->>AI: Extract ArcFace 512D Embedding
        Worker->>Cache: Cosine Similarity Search (girls_hostel)
        alt Cache Miss
            Worker->>DB: Execute girls_hostel.match_face(embedding)
            DB-->>Worker: Matched student_id & roll_number
        else Cache Hit
            Cache-->>Worker: Matched student_id & roll_number
        end

        Worker->>FSM: Process Event (Student ID, Camera ID, Timestamp)
        FSM->>FSM: Check 15s Anti-bounce Cooldown
        alt Cooldown Passed
            FSM->>DB: UPDATE girls_hostel.student_profiles SET current_status = direction
            FSM->>DB: INSERT INTO girls_hostel.movement_logs (student_id, direction, camera_id)
        end
    end
```

---

## 5. Security & Row-Level Access Policy
- **Database Row Level Security (RLS)**:
  - Enabled on `girls_hostel.student_profiles`, `girls_hostel.movement_logs`, and `girls_hostel.curfew_alerts`.
  - Direct public access via `anon` role is **DENIED**.
  - Read access for authenticated warden users is restricted via role policy.
  - Flask backend uses `SUPABASE_SERVICE_ROLE_KEY` to execute administrative writes safely.
