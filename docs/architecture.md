# 🏗️ System Architecture Guide

This document describes the design patterns, application structure, and execution lifecycles of **BioSecure AI — Girls Hostel Management Platform**, including both the **High-FPS Multithreaded Live Camera Engine** and the **Biometric Embedding Drift Engine**.

---

## 📁 Enterprise Directory Structure

BioSecure AI follows an enterprise **Modular Flask Blueprint** architecture:

```
BioSecure AI - GIrls Hostel/
├── docs/                        # Complete System Documentation Hub
│   ├── index.md                 # Documentation Portal Index
│   ├── architecture.md          # Architecture & Multithreaded Camera Specs
│   ├── api_reference.md         # Full REST & MJPEG API Specification
│   ├── database.md              # SQLite Schema & Movement Log Tables
│   ├── deployment.md            # Production Setup (Nginx, Gunicorn, Systemd)
│   ├── ml_pipeline.md           # InsightFace 512D ML & EWMA Drift Math
│   ├── user_guide.md            # Warden & Admin User Manual
│   └── specifications/          # Architecture, PRD, SAD, TAD, FAD Specs
├── nginx/                       # Reverse Proxy Configuration
├── scripts/                     # Database Schemas & Setup Scripts
├── src/                         # Application Source Code
│   ├── __init__.py            # Flask Application Factory
│   ├── config.py              # Configuration & Threshold Constants
│   ├── blueprints/            # Blueprint Route Modules (Controllers)
│   │   ├── admin.py           # User management, /admin/drift, resets
│   │   ├── attendance.py      # Attendance processing & manual marks
│   │   ├── auth.py            # Session authentication & login
│   │   ├── hostel.py          # Warden control center & /hostel/video_feed
│   │   └── students.py        # Student records & guided enrollment
│   ├── services/              # Core Services Layer
│   │   ├── curfew_service.py  # Curfew violations processor
│   │   └── hostel_camera.py   # Asynchronous High-FPS Multithreaded Camera Engine
│   ├── utils/                 # Utilities & Biometric Helpers
│   │   ├── hostel_db.py       # SQLite WAL database operations
│   │   ├── face.py            # InsightFace ArcFace 512D inference
│   │   └── face_cache.py      # In-memory numpy matrix face matching
│   ├── templates/             # Jinja2 HTML Templates
│   └── static/                # CSS, JS, and asset files
├── tests/                       # Automated Test Suite (Pytest)
├── app.py                       # Development Entrypoint
├── wsgi.py                      # Production WSGI Entrypoint
├── gunicorn.conf.py            # Gunicorn Server Settings
├── start_hostel.sh              # Unix/Linux Service Launcher
├── start_hostel.bat             # Windows Service Launcher
└── requirements.txt             # Dependency Definitions
```

---

## 🔄 Multithreaded Camera Engine & Video Streaming Architecture

To guarantee **30+ FPS video streaming** on warden dashboards while executing compute-heavy InsightFace AI detection on CPU, camera frame capture is decoupled from AI inference using two dedicated background threads:

```mermaid
sequenceDiagram
    autonumber
    participant Cam as OpenCV Video Device (cap.read)
    participant Engine as HostelCameraManager
    participant Thread1 as Stream Loop Thread (_camera_loop)
    participant Thread2 as Async AI Worker Thread (_ai_worker_loop)
    participant Client as Warden Browser Dashboard

    Cam->>Thread1: Read Video Frame @ 30 FPS
    Thread1->>Engine: Store latest frame in memory (latest_small_frame)
    Thread1->>Engine: Read cached face overlays
    Thread1->>Thread1: Draw bounding box & status label on frame
    Thread1->>Thread1: Encode JPEG & write to /tmp/hostel_live_frame.jpg
    Thread1-->>Client: Yield frame over persistent MJPEG stream (/hostel/video_feed)

    loop Asynchronous AI Inference (In Parallel)
        Thread2->>Engine: Fetch latest_small_frame from memory
        Thread2->>Thread2: Run InsightFace 512D ArcFace model
        Thread2->>Thread2: Match embeddings against student face cache
        Thread2->>Thread2: Evaluate Verification Rules (Dual-Tier Thresholds)
        alt Verified Match
            Thread2->>Thread2: Check student current_status (IN / OUT)
            Thread2->>Thread2: Enforce 15-second cooldown
            Thread2->>Engine: Auto-log entry/exit movement to SQLite WAL DB
        end
        Thread2->>Engine: Update cached_overlays atomically
    end
```

---

## ⚡ Concurrency & Scaling Principles

1. **Decoupled Video & AI Loop**: Video frames flow to the client at hardware speed (30–60 FPS) without pausing for AI inference.
2. **Configurable Frame Skipping**: `CAMERA_FRAME_SKIP_COUNT` (default `4`) allows tuning AI detection frequency. Face recognition runs asynchronously every $N$ frames (~120–150ms), keeping bounding box updates responsive while preserving smooth 30 FPS video playback.
3. **Dashboard Frame Refresh Control**: Front-end dashboards update live camera elements using `CAMERA_REFRESH_INTERVAL_MS` (default `40` ms / ~25 FPS) for fluid video playback without browser rendering lag.
4. **Persistent Native MJPEG Streaming**: Serves live camera video via a single HTTP multipart connection (`/hostel/video_feed`), eliminating client-side HTTP GET polling overhead.
5. **Process-Level Lock**: Uses `fcntl.flock` on `/tmp/hostel_camera_device.lock` so that only one primary Gunicorn worker opens the physical USB camera device, avoiding hardware conflicts.
6. **SQLite WAL (Write-Ahead Logging) Mode**: Configured with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` to allow concurrent database reads and writes across multiple threads and worker processes.

