# 🌍 Production Deployment Guide

This document provides production setup instructions for **BioSecure AI — Girls Hostel Security System** using **Gunicorn**, **Nginx**, and **Systemd** on Linux production servers.

---

## 🛠️ Environment Variables Reference (.env)

Create a production `.env` file from [.env.example](file:///home/dell/BioSecure%20AI%20-%20GIrls%20Hostel/.env.example):

```ini
# Flask Secrets
FLASK_SECRET_KEY="your-secure-production-random-secret"

# Supabase Credentials (Optional for local SQLite WAL)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# InsightFace Execution Device
# 0 = CUDA GPU Execution, -1 = CPU Execution (Default: -1)
INSIGHTFACE_CTX_ID=-1

# Face Matching Parameters
FACE_MATCH_THRESHOLD=0.3
REATTENDANCE_INTERVAL_MINUTES=10

# Camera & High-FPS Performance Tuning
CAMERA_FRAME_SKIP_COUNT=4       # AI face scan skipped frame interval (default: 4)
CAMERA_REFRESH_INTERVAL_MS=40    # Live dashboard frame update interval (~25 FPS)

# Biometric Embedding Drift Detection (Pose-Gated EWMA)
DRIFT_ALPHA=0.3                 # EWMA smoothing factor
DRIFT_POSE_YAW_MAX=25.0         # Maximum yaw angle for drift processing (deg)
DRIFT_POSE_PITCH_MAX=20.0       # Maximum pitch angle for drift processing (deg)
DRIFT_WARN_THRESHOLD=0.15       # Warning alert threshold
DRIFT_CRITICAL_THRESHOLD=0.25   # Critical alert threshold
DRIFT_ALERT_THRESHOLD=0.35     # Severe alert threshold
```

---


## 🚀 Production Deployment Stack

### 1. Install System Dependencies
Install Python 3.10+, virtual environment tools, and OpenCV system packages on Ubuntu/Debian:
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libgl1-mesa-glx libglib2.0-0 nginx
```

### 2. Prepare Virtual Environment & Dependencies
```bash
cd "/var/www/BioSecure AI - GIrls Hostel"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Systemd Service Daemon (`/etc/systemd/system/biosecure-hostel.service`)

```ini
[Unit]
Description=BioSecure AI Girls Hostel Warden Platform
After=network.target

[Service]
User=dell
WorkingDirectory=/var/www/BioSecure AI - GIrls Hostel
ExecStart=/var/www/BioSecure AI - GIrls Hostel/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable biosecure-hostel
sudo systemctl start biosecure-hostel
```

---

## 🌐 Nginx Reverse Proxy Configuration (`nginx/nginx.conf`)

For real-time MJPEG camera streaming (`/hostel/video_feed`), **Nginx proxy buffering must be disabled** to stream frames without latency.

Create `/etc/nginx/sites-available/biosecure-hostel`:

```nginx
server {
    listen 80;
    server_name hostel.coer.ac.in;

    client_max_body_size 50M;

    # General Route Proxy
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # High-FPS Unbuffered MJPEG Camera Stream
    location /hostel/video_feed {
        proxy_pass http://127.0.0.1:5000;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_read_timeout 86400s;
    }
}
```

Enable Nginx configuration and reload:
```bash
sudo ln -s /etc/nginx/sites-available/biosecure-hostel /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```
