# 📋 Product Requirements Document (PRD) — BioSecure AI: Girls Hostel Entry/Exit & Curfew Security System

## 1. Executive Summary
**BioSecure AI - Girls Hostel Edition** is an automated, real-time computer vision and biometric monitoring system designed specifically for girls' hostel security management. The system monitors two independent camera feeds—**Camera 1 (Entry / Returning Students)** and **Camera 2 (Exit / Outgoing Students)**—detecting multiple students simultaneously. It logs movements (`OUT` and `IN` with timestamps) and automatically monitors curfew compliance during a configurable time window (e.g., System Start: **5:00 PM / 17:00**, Curfew Deadline: **7:30 PM / 19:30**). Any student who remains outside past the curfew deadline triggers instant system alerts for hostel wardens and security personnel.

To prevent any cross-contamination or impact on existing institutional data (such as classroom attendance), this system operates on a completely isolated PostgreSQL schema (`girls_hostel`) within the shared database instance.

---

## 2. Problem Statement & Objectives
### 2.1 Problem Statement
Traditional hostel register management relies on manual physical logbooks or single-point biometric scanners, resulting in:
- Long queues at entry/exit gates during peak hours.
- Human error and delayed reporting of tardy or missing students.
- Inability to quickly identify students who have failed to return before curfew.
- Risk of data corruption or privacy leak when hostel logs mingle with general academic attendance systems.

### 2.2 Core Objectives
1. **Dual-Camera Live Streaming & Multi-Face Detection**: Simultaneously ingest and process real-time feeds from Camera 1 (Entry) and Camera 2 (Exit), identifying multiple student faces per frame without manual intervention.
2. **Automated Movement Logging**: Instantly record movement logs with accurate timestamps (`student_id`, `direction: IN/OUT`, `camera_id`, `timestamp`, `confidence`).
3. **Curfew Window & Overdue Alert Engine**: Maintain a configurable curfew monitoring schedule (default: 5:00 PM to 7:30 PM). Automatically flag and alert wardens about students who are currently `OUT` past the curfew cutoff.
4. **Strict Database Schema Isolation**: Create and execute all operations strictly within the `girls_hostel` schema in Supabase PostgreSQL (`pgvector`), ensuring student embeddings, logs, and RPC functions remain completely isolated from other projects.

---

## 3. User Personas & Roles

| Persona / Role | Key Responsibilities | Access Level | Primary Needs |
|---|---|---|---|
| **Hostel Warden** | Monitors live gate streams, reviews overdue curfew alerts, manages student registrations. | `hostel_admin` / Warden Dashboard | Real-time overdue alert list, immediate contact info, daily exit/entry summaries. |
| **Security Gate Staff** | Observes live video streams at entry/exit points, verifies flagged alerts. | `hostel_security` View | High-speed multi-face identification overlay, visual verification cards. |
| **System Administrator** | Configures curfew windows, manages camera RTSP feeds, inspects schema integrity. | `system_admin` | Schema maintenance, system diagnostics, API rate controls. |

---

## 4. Key Functional Requirements

### FR-1: Dual Camera Video Ingestion & Real-Time Processing
- **FR-1.1**: The system MUST support two simultaneous camera feeds:
  - `CAM_01_ENTRY`: Positioned at the entry gate facing incoming students.
  - `CAM_02_EXIT`: Positioned at the exit gate facing outgoing students.
- **FR-1.2**: Multi-face detection MUST identify up to 10 faces simultaneously per camera frame using InsightFace RetinaFace/ArcFace.
- **FR-1.3**: Inference speed MUST maintain $\le 200\text{ ms}$ processing time per frame batch.

### FR-2: Schema-Isolated Biometric Recognition
- **FR-2.1**: Student face embeddings (512-dimensional vector) MUST be stored strictly in `girls_hostel.student_profiles`.
- **FR-2.2**: Vector similarity queries MUST call a schema-scoped PostgreSQL RPC function `girls_hostel.match_face`.
- **FR-2.3**: Cosine similarity match threshold MUST be configurable (default: `0.40`).

### FR-3: Movement State Machine & Cooldown Logic
- **FR-3.1**: System MUST maintain the current location status of each student (`IN` or `OUT`).
- **FR-3.2**: When a face is detected at `CAM_02_EXIT`:
  - If current status is `IN`, change status to `OUT` and write a movement log entry with `direction = 'OUT'`.
- **FR-3.3**: When a face is detected at `CAM_01_ENTRY`:
  - If current status is `OUT`, change status to `IN` and write a movement log entry with `direction = 'IN'`.
- **FR-3.4**: An anti-bounce cooldown window (default: 15 seconds) MUST prevent duplicate log entries when a student remains in front of the camera.

### FR-4: Curfew Schedule & Automated Overdue Alerting Engine
- **FR-4.1**: System MUST support configurable Curfew System Start Time (e.g., `17:00` / 5:00 PM) and Curfew Deadline Time (e.g., `19:30` / 7:30 PM).
- **FR-4.2**: At the curfew deadline (e.g. 7:30 PM) and on periodic background scans thereafter, the system MUST query `girls_hostel.student_profiles WHERE current_status = 'OUT'`.
- **FR-4.3**: All identified overdue students MUST be populated into `girls_hostel.curfew_alerts` and broadcasted in real time to the Warden Dashboard UI.
- **FR-4.4**: System MUST support optional SMTP email / SMS alerts to hostel authorities detailing overdue students and parent contact information.

---

## 5. Non-Functional Requirements (NFRs)

- **NFR-1 (Database Isolation)**: All tables, sequences, indexes, and stored procedures MUST reside within `girls_hostel` schema. Queries to `public` tables are strictly prohibited.
- **NFR-2 (Performance & Latency)**: Face detection and matching latency MUST be under $200\text{ ms}$ per camera frame. Real-time stream rendering MUST maintain $\ge 15\text{ FPS}$.
- **NFR-3 (Accuracy & Precision)**: ArcFace 512D recognition precision MUST exceed $99.2\%$ on compliant frontal/near-frontal face samples.
- **NFR-4 (Security & Compliance)**: Row-Level Security (RLS) MUST be enabled on all `girls_hostel` tables, granting access exclusively through authenticated backend service keys.
- **NFR-5 (Reliability & Failover)**: In the event of network disruption, camera feeds MUST auto-reconnect without crashing the core web application.

---

## 6. Success Metrics & KPIs
- **100% Curfew Compliance Visibility**: Zero un-flagged overdue exits past 7:30 PM.
- **0% Cross-Schema Data Pollution**: Zero records created in or read from `public` schema.
- **< 15 sec Gate Throughput**: Processing multi-student groups without requiring students to stop and queue single-file.
