# 📐 System Architecture & End-to-End Blueprint — BioSecure AI: Girls Hostel System

## 1. System Vision
The **BioSecure AI - Girls Hostel System** is an enterprise-grade automated gate security and curfew monitoring application. It handles simultaneous multi-face detection across two cameras, maintains student entry/exit state transitions, and enforces strict curfew policies (System Start: **5:00 PM / 17:00**, Curfew Deadline: **7:30 PM / 19:30**).

Crucially, the entire system operates under complete database isolation within a dedicated PostgreSQL schema (`girls_hostel`), ensuring zero interference with existing academic attendance or other institutional datasets.

---

## 2. End-to-End Modular Architecture

```mermaid
graph TB
    subgraph Layer_1_Cameras["Dual Edge Video Layer"]
        CAM1["Camera 01: ENTRY (Returning Students)"]
        CAM2["Camera 02: EXIT (Outside-Going Students)"]
    end

    subgraph Layer_2_Processing["Python Flask ML Ingestion Engine"]
        CV_WORKER["Dual-Thread Ingestion Worker (OpenCV / RTSP)"]
        DETECTOR["InsightFace RetinaFace Multi-Face Detector"]
        EXTRACTOR["InsightFace ArcFace 512D Extractor"]
        COOLDOWN["15s Anti-Bounce Cooldown Gate"]
        FSM["Hostel Movement State Machine (IN ↔ OUT)"]
    end

    subgraph Layer_3_Isolated_DB["Supabase PostgreSQL Cloud (Isolated)"]
        subgraph Isolated_Schema["girls_hostel Schema"]
            SP["girls_hostel.student_profiles"]
            ML["girls_hostel.movement_logs"]
            CA["girls_hostel.curfew_alerts"]
            SS["girls_hostel.system_settings"]
            RPC["girls_hostel.match_face() RPC"]
        end
        subgraph Standard_Schema["public Schema (Unaffected)"]
            PUB_SP["public.student_profiles"]
            PUB_AL["public.attendance_logs"]
        end
    end

    subgraph Layer_4_Curfew_Engine["Curfew & Overdue Alert Engine"]
        SCHEDULER["Background Cron Worker (Every 60s)"]
        RULE_EVAL["Rule Evaluator (5:00 PM - 7:30 PM Window)"]
        DISPATCHER["Multi-Channel Alert Dispatcher (SMTP / Dashboard)"]
    end

    subgraph Layer_5_UI["Hostel Management Web Portal"]
        STREAM_UI["Live Dual-Camera Stream View"]
        LOGS_UI["Real-Time Movement Logs Table"]
        ALERTS_UI["Curfew Overdue Alert Banner & Action Portal"]
    end

    CAM1 --> CV_WORKER
    CAM2 --> CV_WORKER
    CV_WORKER --> DETECTOR
    DETECTOR --> EXTRACTOR
    EXTRACTOR --> RPC
    RPC --> SP
    SP --> FSM
    FSM --> COOLDOWN
    COOLDOWN --> ML
    
    SCHEDULER --> RULE_EVAL
    RULE_EVAL -->|Query OUT Students| SP
    RULE_EVAL -->|Write Overdue Record| CA
    CA --> DISPATCHER
    
    ML --> LOGS_UI
    CA --> ALERTS_UI
    CV_WORKER --> STREAM_UI
```

---

## 3. Detailed Data Flow Architecture

### 3.1 Exit Gate Event Flow (`CAM_02_EXIT`)
1. Student approaches Exit Gate between 5:00 PM and 7:30 PM.
2. `CAM_02_EXIT` captures frame $\to$ RetinaFace detects face bounding box $\to$ ArcFace extracts 512D embedding vector.
3. System executes `girls_hostel.match_face(query_embedding, threshold=0.40)`.
4. Result returned: Student matched (`roll_number`, `name`, `current_status`).
5. Anti-bounce check validates last movement timestamp (> 15 seconds).
6. State Machine transitions student `current_status` from `'IN'` $\to$ `'OUT'`.
7. Record created in `girls_hostel.movement_logs` (`direction = 'OUT'`, `camera_id = 'CAM_02_EXIT'`, `timestamp = now()`).
8. Live movement feed on Warden Dashboard updates instantly.

### 3.2 Entry Gate Event Flow (`CAM_01_ENTRY`)
1. Student returns to Entry Gate.
2. `CAM_01_ENTRY` captures frame $\to$ Face matched via `girls_hostel.match_face`.
3. State Machine transitions student `current_status` from `'OUT'` $\to$ `'IN'`.
4. Record created in `girls_hostel.movement_logs` (`direction = 'IN'`, `camera_id = 'CAM_01_ENTRY'`, `timestamp = now()`).
5. If student had an active overdue alert, system marks the alert status as `'RESOLVED'` with `resolved_at = now()`.

---

## 4. Curfew Enforcement Architecture

```mermaid
sequenceDiagram
    autonumber
    participant Clock as System Clock (Server Time)
    participant Cron as Curfew Worker Thread
    participant DB as Supabase (girls_hostel Schema)
    participant UI as Warden Dashboard
    participant SMTP as Email Dispatcher

    Clock->>Cron: Trigger Cron Scan (Every 60s)
    Cron->>Cron: Check if Current Time >= 19:30 (7:30 PM)
    alt Time >= 19:30 PM
        Cron->>DB: SELECT * FROM girls_hostel.student_profiles WHERE current_status = 'OUT'
        DB-->>Cron: List of OUT Students [Student_A, Student_B]
        loop For each OUT student
            Cron->>DB: Check if curfew_alerts already has active OVERDUE_OUT record
            alt Record Missing
                Cron->>DB: INSERT INTO girls_hostel.curfew_alerts (student_id, status='OVERDUE_OUT')
                Cron->>UI: Broadcast WebSocket / SSE Overdue Event
                Cron->>SMTP: Dispatch Alert Email with Student & Parent Info
            end
        end
    end
```

---

## 5. Schema Isolation Verification Matrix

| Entity | `girls_hostel` Schema (New) | `public` Schema (Existing) | Impact |
|---|---|---|---|
| **Student Profiles** | `girls_hostel.student_profiles` | `public.student_profiles` | **100% Isolated** |
| **Attendance / Logs** | `girls_hostel.movement_logs` | `public.attendance_logs` | **100% Isolated** |
| **Curfew / Overdue** | `girls_hostel.curfew_alerts` | N/A | **100% Isolated** |
| **Vector Match RPC** | `girls_hostel.match_face()` | `public.match_face()` | **100% Isolated** |
| **System Settings** | `girls_hostel.system_settings` | N/A | **100% Isolated** |
