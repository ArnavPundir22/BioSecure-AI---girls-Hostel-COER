# Original User Request

## Initial Request — 2026-09-09T04:55:40Z

Build the BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System. The system detects identified girl students entering (Camera 1) or leaving (Camera 2) the hostel, logs movement timestamps (`IN`/`OUT`), and enforces configurable curfew windows (System Start: 5:00 PM / 17:00, Curfew Deadline: 7:30 PM / 19:30), generating real-time overdue alerts for students who remain outside past curfew. All data, embeddings, logs, and RPC functions operate inside a dedicated, isolated PostgreSQL schema (`girls_hostel`) with zero impact on existing classroom attendance or other projects' data.

Working directory: `/home/dell/BioSecure AI - GIrls Hostel`
Integrity mode: development

## Requirements

### R1. Isolated PostgreSQL Schema Migration (`girls_hostel`)
Implement a comprehensive SQL schema migration under the dedicated `girls_hostel` PostgreSQL schema. Create tables `girls_hostel.student_profiles`, `girls_hostel.movement_logs`, `girls_hostel.curfew_alerts`, and `girls_hostel.system_settings`. Create an HNSW vector index on 512D ArcFace embeddings and deploy the `girls_hostel.match_face` RPC function. Ensure zero access or operational impact on the `public` schema.

### R2. Dual Camera Ingestion & Multi-Face Detection
Build real-time video stream ingestion workers for Camera 1 (Entry Gate - returning students) and Camera 2 (Exit Gate - outgoing students). Detect multiple faces simultaneously in each frame using InsightFace (RetinaFace + ArcFace 512D) with sub-200ms processing delay per frame batch.

### R3. Movement State Machine & Cooldown Engine
Implement a hostel movement state engine tracking each student's current status (`IN` vs `OUT`). When Camera 2 detects a student currently `IN`, transition state to `OUT` and write a movement log. When Camera 1 detects a student currently `OUT`, transition state to `IN` and write a movement log. Enforce a 15-second anti-bounce cooldown per student per camera stream.

### R4. Curfew Schedule & Overdue Alert Scanner
Develop a background curfew monitoring service operating under configurable window settings (System Start: 17:00 / 5:00 PM, Curfew Cutoff: 19:30 / 7:30 PM). At 7:30 PM and on periodic background scans thereafter, query all students with `current_status = 'OUT'`, flag them in `girls_hostel.curfew_alerts`, and trigger real-time warden alerts and SMTP email notifications.

### R5. Warden Dashboard & Control Center UI
Build a dark glassmorphic Flask web interface (`/hostel`) featuring dual live camera stream feeds, a real-time movement logs table, active overdue alert cards with parent contact details, and manual alert resolution controls.

## Acceptance Criteria

### Schema Isolation & Security
- [ ] All database DDL, queries, vector lookups, and RPC functions operate strictly within `girls_hostel.*`.
- [ ] No reads, writes, or references are made to `public.student_profiles` or `public.attendance_logs`.
- [ ] Supabase Row Level Security (RLS) is enabled on all `girls_hostel` tables.

### Dual Stream Multi-Face Recognition
- [ ] Camera 1 (Entry) and Camera 2 (Exit) streams process frames simultaneously without stream dropping.
- [ ] Detects up to 10 student faces per frame concurrently with frame latency under 200ms.

### Movement State Machine & Cooldown
- [ ] Camera 2 (Exit) logs movement direction `OUT` and updates student status to `OUT`.
- [ ] Camera 1 (Entry) logs movement direction `IN` and updates student status to `IN`.
- [ ] 15-second anti-bounce timer prevents duplicate log entries when a face lingers in camera view.

### Curfew & Overdue Alert Enforcement
- [ ] Curfew window is configurable (default: 5:00 PM start, 7:30 PM curfew cutoff).
- [ ] Students remaining `OUT` past 7:30 PM are automatically logged as `OVERDUE_OUT` in `girls_hostel.curfew_alerts`.
- [ ] Warden Dashboard highlights overdue students in real-time alert panels with student and parent contact info.
