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

## Follow-up — 2026-09-10T04:23:56Z

Build an Enterprise-Grade CCTV & Camera Setup Management System for BioSecure AI Girls Hostel, supporting seamless RTSP/DVR dual-gate camera feeds (IN & OUT gates), automatic testing & live UI preview, brand presets, robust fallback to local webcams, Supabase DB setting persistence, and zero-downtime error resilience in production.

Working directory: /home/dell/BioSecure AI - GIrls Hostel
Integrity mode: development

## Requirements

### R1. Enterprise Camera Setup UI & Vendor Presets
Provide a dedicated visual UI in the Admin Dashboard (`/admin/cameras` or embedded tab in `admin_dashboard.html`) for configuring camera connections for IN and OUT gates. Support vendor presets for major DVR/CCTV brands (Hikvision, CP Plus, Dahua, TVT, Generic RTSP) as well as USB Webcams, allowing admins to enter IP, port, channel, username, and password without manually editing code or `.env`.

### R2. Live Connection Probing & Real-Time Stream Preview
Implement a backend stream prober endpoint (e.g. `/api/cameras/test-connection`) and frontend live preview modal/canvas on the Camera Management UI so administrators can test connections, verify RTSP authentication, view resolution/FPS latency metrics, and preview live feeds before saving.

### R3. Supabase DB Persistence & Hot Configuration Reloading
Store camera configurations securely in Supabase DB (`girls_hostel.camera_settings` or dedicated configuration table) so settings sync across all server processes. When an admin saves camera settings in the UI, trigger a hot reload of the background stream managers without restarting the Flask/Gunicorn server.

### R4. Resilient Dual-Gate RTSP Stream Engine with Auto-Fallback
Refactor the camera management engine (`src/services/hostel_camera.py`) to run concurrent IN Gate and OUT Gate stream background workers:
- Stream Channel 1 (IN Gate) -> trigger student `IN` movement log.
- Stream Channel 2 (OUT Gate) -> trigger student `OUT` movement log.
- Zero-Crash Resilience: If an RTSP feed disconnects, encounters network timeout, or drops frames, handle errors gracefully with non-blocking reconnection loops and automatic fallback to host webcam / placeholder frame.

### R5. Decoupled Client Browser WebRTC Student Registration
Ensure student face registration on `/add_student` continues to use the warden's client browser camera (via WebRTC `navigator.mediaDevices.getUserMedia`), keeping registration completely independent from server/DVR camera feeds.

## Acceptance Criteria

### UI & Configuration Management
- [ ] Admin dashboard provides an intuitive, responsive Camera Management UI for IN and OUT gates with vendor dropdowns (Hikvision, CP Plus, Dahua, TVT, Custom RTSP, USB Webcam).
- [ ] "Test Connection" button probes RTSP streams and renders a live preview image with stream stats (status, resolution, FPS).
- [ ] Camera configurations persist cleanly in Supabase DB and load automatically on application startup.

### Production Stream Stability & Gate Logging
- [ ] Zero crash guarantee: Network dropouts, bad RTSP credentials, or DVR reboots do not throw unhandled exceptions or crash Gunicorn/Flask workers.
- [ ] IN and OUT gate camera feeds process concurrently and log accurate movement records (`gate: 'IN'` or `gate: 'OUT'`) to Supabase `movement_logs`.
- [ ] Automated or manual verification confirms camera configuration hot-reloading works without server restarts.
