# Original User Request

## 2026-09-09T04:56:10Z

You are the Project Orchestrator for the BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System project.

Your working directory is: `/home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator`
The workspace root directory is: `/home/dell/BioSecure AI - GIrls Hostel`
The authoritative user request is in: `/home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md`

Your tasks:
1. Read `/home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md`.
2. Initialize your BRIEFING.md, plan.md, and progress.md in your working directory.
3. Decompose the project into milestones based on requirements (R1: Isolated PostgreSQL Schema Migration under `girls_hostel`, R2: Dual Camera Ingestion & Multi-Face Detection, R3: Movement State Machine & Cooldown Engine, R4: Curfew Schedule & Overdue Alert Scanner, R5: Warden Dashboard & Control Center UI).
4. Dispatch specialist subagents to implement, test, and verify each milestone according to the Acceptance Criteria.
5. Strictly adhere to architectural constraints: zero references/reads/writes to `public` schema (`public.student_profiles`, `public.attendance_logs`), full Supabase RLS on `girls_hostel` tables, sub-200ms latency, 15-second cooldown timer, automated curfew alerts, and dark glassmorphic UI.
6. Keep progress.md regularly updated with milestones, status, and verification results.
7. When all milestones are verified and acceptance criteria are met, report project completion to the Sentinel.

## 2026-09-10T04:24:56Z

You are the Project Orchestrator for BioSecure AI Girls Hostel CCTV Camera Setup Management System.
Your working directory is /home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator.
The project root is /home/dell/BioSecure AI - GIrls Hostel.
Read the authoritative user request at /home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md (specifically the latest follow-up under ## Follow-up — 2026-09-10T04:23:56Z).

Scope & Requirements:
Build an Enterprise-Grade CCTV & Camera Setup Management System for BioSecure AI Girls Hostel:
- R1. Enterprise Camera Setup UI & Vendor Presets: Visual UI in Admin Dashboard (/admin/cameras or embedded tab in admin_dashboard.html), vendor presets for Hikvision, CP Plus, Dahua, TVT, Custom RTSP, and USB Webcams, allowing admins to configure IP, port, channel, username, password without editing code/.env.
- R2. Live Connection Probing & Real-Time Stream Preview: Backend stream prober endpoint (e.g. /api/cameras/test-connection) and frontend live preview modal/canvas on Camera Management UI with stream stats (status, resolution, FPS latency metrics).
- R3. Supabase DB Persistence & Hot Configuration Reloading: Store camera configurations in Supabase DB (girls_hostel.camera_settings or dedicated config table) syncing across processes. Hot reload of background stream managers on save without restarting Flask/Gunicorn.
- R4. Resilient Dual-Gate RTSP Stream Engine with Auto-Fallback: Refactor src/services/hostel_camera.py to run concurrent IN Gate (Channel 1 -> IN movement log) and OUT Gate (Channel 2 -> OUT movement log) background workers. Zero-crash resilience: non-blocking reconnection loops and automatic fallback to host webcam / placeholder frame.
- R5. Decoupled Client Browser WebRTC Student Registration: Ensure student face registration on /add_student continues using the warden's client browser camera via WebRTC getUserMedia, remaining completely independent from server/DVR feeds.

Also maintain all existing acceptance criteria and schema isolation under girls_hostel.*.

Follow your standard orchestration lifecycle:
1. Initialize/update your BRIEFING.md, PROJECT.md, plan.md, and progress.md in /home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator.
2. Decompose into milestones and dispatch specialists (Explorers, Workers, Reviewers, Challengers, Forensic Auditor) for implementation and verification.
3. Keep progress.md updated regularly with timestamps and milestone status.
4. When all acceptance criteria and milestones are complete and verified, send a completion report claiming victory to Sentinel so a Victory Auditor can be dispatched.
Begin execution immediately.
