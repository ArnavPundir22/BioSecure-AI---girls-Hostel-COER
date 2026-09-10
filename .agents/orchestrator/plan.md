# Project Execution Plan: BioSecure AI - Girls Hostel CCTV Camera Setup Management System

## Strategy Overview
Adhere strictly to the Project Pattern:
1. **Milestone CCTV**: Enterprise-Grade CCTV Camera Setup Management System (R1-R5).
2. **Iteration Loop**:
   - **Step 1: Exploration (3 Explorers)**
     - Explorer 1 (`explorer_cctv_1`): `src/services/hostel_camera.py` deep-dive. Dual-gate concurrent stream workers (IN Gate Ch 1 -> 'IN', OUT Gate Ch 2 -> 'OUT'), zero-crash resilience, non-blocking reconnection loop, auto-fallback to host webcam / placeholder frame.
     - Explorer 2 (`explorer_cctv_2`): Database persistence & hot reload. `girls_hostel.camera_settings` schema, `src/utils/hostel_db.py`, DB migrations, load on startup, thread/process-safe hot-reload mechanism without Flask/Gunicorn restarts.
     - Explorer 3 (`explorer_cctv_3`): Admin UI & Prober endpoint. `/admin/cameras` UI with vendor presets (Hikvision, CP Plus, Dahua, TVT, Custom RTSP, USB Cam), prober endpoint `/api/cameras/test-connection`, preview modal/canvas with stats (status, resolution, FPS latency), and WebRTC decoupling verification on `/add_student`.
   - **Step 2: Implementation (1 Worker)**
     - Implement DB migration and helper methods for `camera_settings`.
     - Refactor `src/services/hostel_camera.py` to support dual-gate workers, vendor RTSP string formatting, connection prober, auto-fallback, and hot-reload.
     - Build UI and endpoints for `/admin/cameras` and `/api/cameras/*`.
     - Verify decoupled WebRTC client student registration on `/add_student`.
     - Write unit and integration tests.
   - **Step 3: Independent Review (2 Reviewers)**
     - Reviewer 1: Correctness, interface conformance, DB schema isolation (`girls_hostel.*`), error resilience.
     - Reviewer 2: Concurrency, hot-reload safety, OpenCV resource management, WebRTC decoupling.
   - **Step 4: Adversarial Testing (2 Challengers)**
     - Challenger 1: Network dropouts, invalid RTSP credentials, port conflicts, DVR reboot simulation.
     - Challenger 2: Rapid hot-reloads, concurrent gate movements, load/stress testing.
   - **Step 5: Forensic Integrity Audit (1 Auditor)**
     - Forensic integrity audit: Verify no hardcoded test responses, genuine OpenCV / RTSP streaming and probing, authentic DB persistence, zero public schema access.
   - **Step 6: Gate & Victory Claim**
     - Pass criteria: All tests pass, no reviewer vetoes, challengers confirm zero crash, auditor issues CLEAN verdict.
     - Report victory to Sentinel.
