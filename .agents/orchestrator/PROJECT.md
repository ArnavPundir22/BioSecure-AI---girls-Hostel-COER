# Project: BioSecure AI - Girls Hostel Entry/Exit & CCTV Setup Management System

## Architecture Overview
The BioSecure AI Girls Hostel Security System is an isolated subsystem operating strictly within the `girls_hostel` PostgreSQL schema. It provides autonomous dual-camera facial biometric entry/exit tracking, state-machine based presence management with anti-bounce cooldown, curfew window schedule enforcement with overdue alerting, a dark glassmorphic real-time Warden Dashboard at `/hostel`, and an Enterprise-Grade CCTV Camera Setup Management System for IN and OUT gates.

```
                         ┌─────────────────────────────────┐
                         │   Camera 1 (IN Gate / Ch 1)     │
                         │   Camera 2 (OUT Gate / Ch 2)    │
                         │   (Hikvision, CP Plus, Dahua,   │
                         │    TVT, Custom RTSP, USB Cam)   │
                         └────────────────┬────────────────┘
                                          │ Resilient Dual RTSP / Fallback Stream
                                          ▼
                         ┌─────────────────────────────────┐
                         │ Dual-Gate Resilient Engine      │
                         │ (src/services/hostel_camera.py) │
                         │ - Non-blocking reconnect loop   │
                         │ - Auto-fallback to local/test   │
                         │ - Hot reload via DB trigger     │
                         │ - Ch 1 -> 'IN' movement log     │
                         │ - Ch 2 -> 'OUT' movement log    │
                         └────────────────┬────────────────┘
                                          │ 512D Embeddings / Detections
                                          ▼
                         ┌─────────────────────────────────┐
                         │   girls_hostel.match_face RPC   │
                         │   (HNSW Cosine Vector Search)   │
                         └────────────────┬────────────────┘
                                          │ Matches (Similarity >= 0.40)
                                          ▼
                         ┌─────────────────────────────────┐
                         │ Movement State & Cooldown Engine│
                         │ - 15s Anti-bounce cooldown      │
                         │ - Cam 1: OUT -> IN              │
                         │ - Cam 2: IN -> OUT              │
                         │ - writes girls_hostel.movement_logs
                         └────────┬───────────────┬────────┘
                                  │               │
       Curfew Background Scanner  │               │ Real-time Updates / SSE
       (17:00 start, 19:30 cutoff)│               │
       flags OVERDUE_OUT in       │               ▼
       girls_hostel.curfew_alerts │    ┌───────────────────────────┐
                                  └───>│  Warden Dashboard UI      │
                                       │  (/hostel, Glassmorphism) │
                                       │  - Dual Live Streams      │
                                       │  - Real-time Movement Log │
                                       │  - Active Overdue Alerts  │
                                       └─────────────┬─────────────┘
                                                     │
                                                     ▼
                                       ┌───────────────────────────┐
                                       │ Camera Setup Management   │
                                       │ (/admin/cameras)          │
                                       │ - Vendor RTSP Presets     │
                                       │ - Prober & Live Preview   │
                                       │ - Supabase DB Persistence │
                                       │ - Zero-Downtime Hot Reload│
                                       └───────────────────────────┘
```

## Database Schema (`girls_hostel` schema only)
- `girls_hostel.student_profiles`: ID, name, roll_number, room_number, hostel_block, parent_contact, student_contact, embedding VECTOR(512), current_status ('IN'/'OUT'), last_movement_time, current_ewma_drift, drift_alert_level, created_at.
- `girls_hostel.movement_logs`: ID, student_id, direction ('IN'/'OUT'), camera_id ('CAM_01_ENTRY'/'CAM_02_EXIT'), timestamp, confidence, snapshot_url.
- `girls_hostel.curfew_alerts`: ID, student_id, curfew_date, system_start_time, curfew_end_time, status ('OVERDUE_OUT'/'RESOLVED'/'EXCUSED'), alert_triggered_at, resolved_at, notes.
- `girls_hostel.system_settings`: key, value JSONB, updated_at.
- `girls_hostel.camera_settings`: id SERIAL PRIMARY KEY, camera_role VARCHAR(20) UNIQUE NOT NULL ('IN' or 'OUT'), vendor VARCHAR(50) NOT NULL, ip_address VARCHAR(100), port INT, channel INT, username VARCHAR(100), password VARCHAR(100), custom_rtsp_url TEXT, resolution VARCHAR(50), fps INT, enabled BOOLEAN DEFAULT TRUE, updated_at TIMESTAMPTZ DEFAULT NOW().
- Vector Index: HNSW on `girls_hostel.student_profiles(embedding vector_cosine_ops)`.
- RPC: `girls_hostel.match_face(query_embedding VECTOR(512), match_threshold FLOAT, match_count INT)`
- Row Level Security (RLS): Enabled on ALL tables in `girls_hostel`. Zero references/reads/writes to `public.*`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|--------------|--------|
| E2E | E2E Testing Suite | Opaque-box test harness covering Tiers 1-4 derived from requirements | None | DONE |
| M1 | Isolated PostgreSQL Schema Migration | scripts/girls_hostel_schema.sql, RLS policies, HNSW index, match_face RPC, DB client utils | None | DONE |
| M2 | Dual Camera Ingestion & Multi-Face Detection | Camera stream ingestion workers (Cam 1 & Cam 2), InsightFace multi-face detector, <200ms latency batching | M1 | DONE |
| M3 | Movement State Machine & Cooldown Engine | State transition engine (IN <-> OUT), 15-second cooldown timer, movement log persistence | M1, M2 | DONE |
| M4 | Curfew Schedule & Overdue Alert Scanner | Background scanner service, configurable curfew window (17:00-19:30), overdue alert generation | M1, M3 | DONE |
| M5 | Warden Dashboard & Control Center UI | Dark glassmorphic UI at /hostel, dual video stream endpoints, live logs table, alert resolution controls | M1-M4 | DONE |
| CCTV | Enterprise CCTV & Camera Setup Management System | R1: Camera Setup UI & Vendor Presets, R2: Stream Prober & Preview Modal, R3: DB Persistence & Hot Reload, R4: Resilient Dual-Gate Stream Engine with Auto-Fallback, R5: Decoupled Browser WebRTC Registration | M1-M5 | DONE |
| FINAL | E2E Suite Verification & Adversarial Hardening | Phase 1: Pass 100% E2E tests; Phase 2: Adversarial coverage hardening; Forensic Integrity Audit | CCTV | PLANNED |

## Interface Contracts

### Camera Management & DB Contract (`src/utils/hostel_db.py`)
- `get_camera_settings(camera_role: str = None) -> list[dict] | dict`: Fetch settings for 'IN', 'OUT', or both from `girls_hostel.camera_settings`.
- `upsert_camera_settings(camera_role: str, settings: dict) -> bool`: Upsert settings into `girls_hostel.camera_settings`.
- `build_rtsp_url(settings: dict) -> str`: Build vendor-specific RTSP stream URL based on preset:
  - Hikvision: `rtsp://[username]:[password]@[ip]:[port]/Streaming/Channels/[channel]01`
  - CP Plus: `rtsp://[username]:[password]@[ip]:[port]/cam/realmonitor?channel=[channel]&subtype=0`
  - Dahua: `rtsp://[username]:[password]@[ip]:[port]/cam/realmonitor?channel=[channel]&subtype=0`
  - TVT: `rtsp://[username]:[password]@[ip]:[port]/ch[channel]/main/av_stream`
  - Custom RTSP: `custom_rtsp_url`
  - USB Webcam: integer index string e.g. `0` or `1`

### Resilient Dual-Gate Engine Contract (`src/services/hostel_camera.py`)
- `HostelCameraManager`:
  - Runs concurrent background workers for IN Gate (Channel 1 -> triggers 'IN' movement log) and OUT Gate (Channel 2 -> triggers 'OUT' movement log).
  - `test_camera_connection(settings: dict) -> dict`: Probes connection, grabs test frame, measures resolution, FPS, latency, and returns base64 thumbnail.
  - `reload_camera_configurations()`: Hot-reloads stream configurations from DB without restarting server.
  - Zero-crash guarantee: Catches OpenCV/RTSP exceptions, handles network timeout/dropouts with non-blocking reconnection loops and automatic fallback to host webcam / placeholder frame.

### Admin Camera Setup Blueprint & Prober Endpoint (`src/blueprints/admin.py` or dedicated)
- `GET /admin/cameras`: Renders responsive Camera Management UI for IN and OUT gates with vendor dropdowns.
- `POST /api/cameras/test-connection`: Backend prober endpoint returning `{success: bool, status: str, resolution: str, fps: float, latency_ms: float, preview_image: str (data URL), error: str}`.
- `POST /api/cameras/save`: Persists settings to DB and triggers hot-reload.
- `GET /api/cameras/settings`: Fetches active settings.

### Decoupled Browser WebRTC Registration (`/add_student`, `src/templates/add_student.html`)
- Preserves client-side WebRTC `navigator.mediaDevices.getUserMedia` for warden registration. Completely decoupled from server CCTV/DVR RTSP feeds.

## Code Layout
- `scripts/girls_hostel_schema.sql` — Schema definition including `girls_hostel.camera_settings`
- `src/utils/hostel_db.py` — Database interface with camera settings persistence and RTSP URL formatting
- `src/services/hostel_camera.py` — Resilient dual-gate RTSP stream manager, connection prober, hot-reload, auto-fallback
- `src/blueprints/admin.py` / `src/blueprints/hostel.py` — Routes for `/admin/cameras` and `/api/cameras/*`
- `src/templates/admin_cameras.html` — Enterprise camera setup UI with vendor presets, testing modal, live preview
- `src/templates/add_student.html` — Decoupled WebRTC client registration
- `tests/unit/test_cctv_camera.py` — Unit tests for presets, prober, persistence, and fallback
- `tests/e2e/test_cctv_management_e2e.py` — E2E test verifying UI, probing, hot-reloading, gate movement logging
