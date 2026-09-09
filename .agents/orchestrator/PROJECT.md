# Project: BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System

## Architecture Overview
The BioSecure AI Girls Hostel Security System is an isolated subsystem operating strictly within the `girls_hostel` PostgreSQL schema. It provides autonomous dual-camera facial biometric entry/exit tracking, state-machine based presence management with anti-bounce cooldown, curfew window schedule enforcement with overdue alerting, and a dark glassmorphic real-time Warden Dashboard at `/hostel`.

```
                         ┌─────────────────────────────────┐
                         │      Camera 1 (Entry Gate)      │
                         │      Camera 2 (Exit Gate)       │
                         └────────────────┬────────────────┘
                                          │ Dual RTSP/Video Streams
                                          ▼
                         ┌─────────────────────────────────┐
                         │   Multi-Face Ingestion Worker   │
                         │   InsightFace (RetinaFace +     │
                         │   ArcFace 512D, <200ms batch)   │
                         └────────────────┬────────────────┘
                                          │ 512D Embeddings
                                          ▼
                         ┌─────────────────────────────────┐
                         │   girls_hostel.match_face RPC   │
                         │   (HNSW Cosine Vector Search)   │
                         └────────────────┬────────────────┘
                                          │ Match Match (Similarity >= 0.40)
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
                                       │  - Alert Resolution CTA   │
                                       └───────────────────────────┘
```

## Database Schema (`girls_hostel` schema only)
- `girls_hostel.student_profiles`: ID, name, roll_number, room_number, hostel_block, parent_contact, student_contact, embedding VECTOR(512), current_status ('IN'/'OUT'), last_movement_time, current_ewma_drift, drift_alert_level, created_at.
- `girls_hostel.movement_logs`: ID, student_id, direction ('IN'/'OUT'), camera_id ('CAM_01_ENTRY'/'CAM_02_EXIT'), timestamp, confidence, snapshot_url.
- `girls_hostel.curfew_alerts`: ID, student_id, curfew_date, system_start_time, curfew_end_time, status ('OVERDUE_OUT'/'RESOLVED'/'EXCUSED'), alert_triggered_at, resolved_at, notes.
- `girls_hostel.system_settings`: key, value JSONB, updated_at.
- Vector Index: HNSW on `girls_hostel.student_profiles(embedding vector_cosine_ops)`.
- RPC: `girls_hostel.match_face(query_embedding VECTOR(512), match_threshold FLOAT, match_count INT)`
- Row Level Security (RLS): Enabled on ALL 4 tables in `girls_hostel`. Service role has full access. Zero references/reads/writes to `public.*`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|--------------|--------|
| E2E | E2E Testing Suite | Opaque-box test harness covering Tiers 1-4 (>=55 test cases) derived from requirements | None | IN_PROGRESS |
| M1 | Isolated PostgreSQL Schema Migration | scripts/girls_hostel_schema.sql, RLS policies, HNSW index, match_face RPC, DB client utils | None | PLANNED |
| M2 | Dual Camera Ingestion & Multi-Face Detection | Camera stream ingestion workers (Cam 1 & Cam 2), InsightFace multi-face detector, <200ms latency batching | M1 | PLANNED |
| M3 | Movement State Machine & Cooldown Engine | State transition engine (IN <-> OUT), 15-second cooldown timer, movement log persistence | M1, M2 | PLANNED |
| M4 | Curfew Schedule & Overdue Alert Scanner | Background scanner service, configurable curfew window (17:00-19:30), overdue alert generation, SMTP notifications | M1, M3 | PLANNED |
| M5 | Warden Dashboard & Control Center UI | Dark glassmorphic UI at /hostel, dual video stream endpoints, live logs table, alert resolution controls | M1-M4 | PLANNED |
| FINAL | E2E Suite Verification & Adversarial Hardening | Phase 1: Pass 100% E2E tests (Tiers 1-4); Phase 2: Adversarial coverage hardening (Tier 5) | E2E, M1-M5 | PLANNED |

## Interface Contracts
### Database Access Contract (`src/utils/hostel_db.py`)
- Schema: Strictly `girls_hostel`.
- Methods:
  - `get_student_by_id(student_id: str) -> dict`
  - `match_face_embedding(embedding: list[float], threshold: float = 0.40) -> list[dict]`
  - `update_student_status(student_id: str, status: str, movement_time: datetime) -> bool`
  - `insert_movement_log(student_id: str, direction: str, camera_id: str, confidence: float, snapshot_url: str = None) -> int`
  - `get_recent_movement_logs(limit: int = 50) -> list[dict]`
  - `get_active_curfew_alerts() -> list[dict]`
  - `create_curfew_alert(student_id: str, curfew_date: date, start_time: str, end_time: str, status: str = 'OVERDUE_OUT') -> int`
  - `resolve_curfew_alert(alert_id: int, status: str, notes: str) -> bool`
  - `get_system_settings(key: str) -> dict`
  - `update_system_settings(key: str, value: dict) -> bool`
  - Zero imports or queries pointing to `public.student_profiles` or `public.attendance_logs`.

### Multi-Face Detector & Camera Ingestion Contract (`src/services/hostel_camera_service.py`)
- Ingestion:
  - `CameraStreamWorker(camera_id: str, source: str/int, role: 'ENTRY'|'EXIT')`
  - Multi-face extraction using InsightFace app (`FaceAnalysis(name='buffalo_sc'|'buffalo_l')`)
  - Target latency: <200ms per batch of up to 10 detected faces
  - Yields detected faces with 512D normalized embedding, bounding box, confidence

### Movement State Machine Contract (`src/utils/hostel_state.py`)
- Engine:
  - `HostelMovementEngine(cooldown_seconds: int = 15)`
  - `process_detection(student_id: str, camera_id: str, confidence: float) -> Optional[dict]`
  - Rules:
    - If camera is ENTRY ('CAM_01_ENTRY') and student is 'OUT': updates status -> 'IN', logs direction='IN'.
    - If camera is EXIT ('CAM_02_EXIT') and student is 'IN': updates status -> 'OUT', logs direction='OUT'.
    - If detection occurs within 15 seconds of previous accepted event for same student & camera: ignore (cooldown active).
    - If student is already 'IN' on ENTRY camera: ignore state change or debounce without error.
    - If student is already 'OUT' on EXIT camera: ignore state change or debounce without error.

### Curfew Scanner Contract (`src/services/curfew_service.py`)
- Service:
  - `HostelCurfewService`
  - `scan_overdue_students() -> list[dict]`
  - Checks if current time >= curfew_end_time (default 19:30) and queries students with `current_status = 'OUT'`.
  - Avoids duplicate active alerts for the same student on the same curfew date.
  - Sends email alert via SMTP if configured.

### Warden Dashboard Contract (`src/blueprints/hostel.py`)
- Routes:
  - `GET /hostel` -> Dark glassmorphic HTML interface
  - `GET /hostel/stream/entry` -> MJPEG live feed for Camera 1 (Entry)
  - `GET /hostel/stream/exit` -> MJPEG live feed for Camera 2 (Exit)
  - `GET /hostel/api/logs` -> JSON list of recent movement logs
  - `GET /hostel/api/alerts` -> JSON list of active curfew alerts
  - `POST /hostel/api/alerts/<id>/resolve` -> Mark alert RESOLVED/EXCUSED
  - `GET /hostel/api/stats` -> Summary statistics (Total Inside, Total Outside, Overdue count)

## Code Layout
- `scripts/girls_hostel_schema.sql` — PostgreSQL schema, tables, indexes, RLS, RPC
- `src/utils/hostel_db.py` — Database interface strictly under `girls_hostel`
- `src/utils/hostel_state.py` — Movement state machine & 15-second cooldown engine
- `src/services/hostel_camera_service.py` — Dual camera stream ingestion & InsightFace recognition worker
- `src/services/curfew_service.py` — Curfew window schedule and overdue scanner
- `src/blueprints/hostel.py` — Flask blueprint for `/hostel` routes and APIs
- `src/templates/hostel_dashboard.html` — Dark glassmorphic Warden Dashboard
- `src/static/css/hostel_dashboard.css` — Modern dark glassmorphic styling
- `src/static/js/hostel_dashboard.js` — Live polling / SSE real-time client updater
- `tests/` — Comprehensive test suite including unit tests, mocks, and E2E tiers 1-5
