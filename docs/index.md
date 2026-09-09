# 🛡️ BioSecure AI — Technical Documentation Hub
### COER University, Roorkee

Welcome to the official technical documentation portal for **BioSecure AI — Girls Hostel Attendance & Gate Security System**.

BioSecure AI is an enterprise-grade automated biometric attendance and gate security system featuring a **High-FPS Multithreaded OpenCV Camera Engine**, **InsightFace 512D ArcFace Recognition**, **Multi-Frame Consensus Verification**, and a **Pose-Gated EWMA Embedding Drift Engine**.

---

## 🗺️ Documentation Hub Navigation

Explore the system through our core documentation modules:

| Document | Description | Key Contents |
| :--- | :--- | :--- |
| 🏗️ **[System Architecture](architecture.md)** | Multithreaded camera engine & system design | Decoupled 30 FPS video streaming thread, Async AI worker thread, SQLite WAL DB |
| 🔌 **[API Reference](api_reference.md)** | Full REST & MJPEG streaming manual | `/hostel/video_feed`, `/process_frame`, `/submit_student`, `/admin/drift` |
| 🗄️ **[Database & Movement Logs](database.md)** | Storage layer & SQLite schemas | `students`, `movement_logs`, `curfew_rules`, SQLite WAL configuration |
| 🧠 **[ML & Inference Pipeline](ml_pipeline.md)** | Facial recognition & drift algorithms | InsightFace ArcFace 512D embeddings, RetinaFace alignment, 3D Pose Gate, EWMA math |
| 🌍 **[Production Ops & Deployment](deployment.md)** | Deployment setup & performance tuning | Gunicorn WSGI configuration, Nginx reverse proxy with zero-buffer streaming |
| 👤 **[User & Warden Guide](user_guide.md)** | Warden & admin operational manual | Interactive guided enrollment, live gate monitoring, curfew tracking, drift resets |
| 📑 **[System Specifications](specifications/)** | Specifications directory | System Architecture Docs (PRD, SAD, TAD, FAD, Rules, Test Infrastructure) |

---

## 🏗️ High-FPS Multithreaded Architecture Overview

```mermaid
graph TD
    Client[Warden Browser Dashboard] -->|Connect to Stream| Nginx[Nginx Reverse Proxy]
    Nginx -->|Proxy Request| Gunicorn[Gunicorn WSGI App]
    Gunicorn -->|/hostel/video_feed| StreamEndpoint[Hostel Video Stream Route]

    subgraph "HostelCameraManager (Multithreaded Service)"
        Cam[Hardware Webcam Device] -->|30 FPS Raw Frames| Thread1[Camera Render Thread _camera_loop]
        Thread1 -->|Encode & Yield JPEG| StreamEndpoint
        Thread1 -->|Shared In-Memory Frame| Lock[Thread Lock Frame Buffer]
        Lock -->|Async Fetch| Thread2[Background AI Worker Thread _ai_worker_loop]
        Thread2 -->|512D Embeddings| AI[InsightFace ArcFace Model]
        AI -->|Batch Cosine Match| Cache[Face Cache Matrix]
        Cache -->|Consensus Verified| DB[(SQLite WAL Database)]
        DB -->|Auto-Log Movement| MovementLogs[girls_hostel.movement_logs]
        Thread2 -->|Update Overlays| Thread1
    end

    style Client fill:#6366f1,stroke:#fafafa,stroke-width:2px,color:#fff
    style StreamEndpoint fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#fff
    style Thread1 fill:#18181b,stroke:#6366f1,stroke-width:2px,color:#fff
    style Thread2 fill:#d97706,stroke:#f59e0b,stroke-width:2px,color:#fff
```

---

## ⚡ Technical Highlights

- **Decoupled 30 FPS Video Streaming**: Camera streaming is decoupled from AI inference, ensuring live feeds on warden dashboards never freeze or drop frames.
- **Persistent MJPEG Multipart Stream**: Uses native HTTP multipart streams (`multipart/x-mixed-replace`) for zero-latency camera rendering in standard `<img>` tags.
- **Dual-Tier Verification Thresholds**:
  - `HIGH_CONFIDENCE_THRESHOLD = 0.36`: Instant match.
  - `MIN_MATCH_THRESHOLD = 0.28`: Base threshold requiring 2 consecutive frame consensus.
- **SQLite WAL Mode**: Thread-safe database operations (`PRAGMA journal_mode=WAL`) optimized for concurrent reads and movement logging writes.
