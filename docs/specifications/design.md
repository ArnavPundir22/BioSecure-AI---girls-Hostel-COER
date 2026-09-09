# 🎨 Technical & UI/UX Design Specifications (design.md) — BioSecure AI: Girls Hostel System

## 1. Overview
This document specifies the UI/UX design, component structure, API specifications, and visual layout for the **BioSecure AI - Girls Hostel Edition**.

---

## 2. UI/UX Design System & Layout Architecture

### 2.1 Aesthetic & Visual Styling
- **Theme**: Dark Glassmorphism (Slate `#0f172a` base, Emerald `#10b981` entry accents, Rose `#f43f5e` alert accents).
- **Typography**: Google Fonts Inter / Outfit for ultra-readable surveillance text.
- **Icons**: Lucide Icons (Shield, Camera, UserCheck, AlertTriangle, Clock).

### 2.2 Dashboard Layout Overview

```
+-----------------------------------------------------------------------------------+
| 🤖 BIOSECURE AI — GIRLS HOSTEL SECURITY MONITOR                     [19:35:12 PM] |
+---------------------------------------------------+-------------------------------+
| LIVE CAMERA FEEDS                                 | ACTIVE OVERDUE ALERTS (2)     |
| +-----------------------+ +---------------------+ | +---------------------------+ |
| | CAM 01: ENTRY [LIVE]  | | CAM 02: EXIT [LIVE]| | | 🚨 ANANYA SHARMA (Block-A) | |
| |                       | |                     | | | OUT since: 17:15 PM      | |
| | [Face Bbox: Matched]  | | [Face Bbox: Matched]| | | Phone: +91 9876543210       | |
| +-----------------------+ +---------------------+ | +---------------------------+ |
+---------------------------------------------------+-------------------------------+
| REAL-TIME MOVEMENT LOGS (girls_hostel.movement_logs)                              |
| +------------------+-------------+------------+--------------------+------------+ |
| | Student Name     | Roll No     | Direction  | Timestamp          | Status     | |
| +------------------+-------------+------------+--------------------+------------+ |
| | Ananya Sharma    | 22001045    | OUT        | 2026-09-09 17:15   | OVERDUE    | |
| | Priya Verma      | 22001088    | IN         | 2026-09-09 19:22   | ON_TIME    | |
| +------------------+-------------+------------+--------------------+------------+ |
+-----------------------------------------------------------------------------------+
```

---

## 3. API Route Specifications

| Method | Route | Description | Request Payload / Params | Response Payload |
|---|---|---|---|---|
| `GET` | `/hostel/` | Renders Main Hostel Warden Dashboard. | None | HTML Render (`hostel_dashboard.html`) |
| `GET` | `/hostel/video_feed/entry` | Stream MJPEG video feed for Camera 01 (Entry). | None | Multipart MJPEG Stream |
| `GET` | `/hostel/video_feed/exit` | Stream MJPEG video feed for Camera 02 (Exit). | None | Multipart MJPEG Stream |
| `GET` | `/api/hostel/stats` | Live summary stats (Total IN, OUT, OVERDUE). | None | `{"total_in": 450, "total_out": 12, "overdue_count": 2}` |
| `GET` | `/api/hostel/movement_logs` | Recent movement logs. | `?limit=50` | `{"logs": [{ "student": "...", "dir": "OUT", ... }]}` |
| `GET` | `/api/hostel/overdue_alerts` | Active overdue alerts list. | None | `{"alerts": [{ "student_name": "...", ... }]}` |
| `POST`| `/api/hostel/resolve_alert` | Manual resolution of an overdue alert by warden. | `{"alert_id": 12, "notes": "Approved late return"}` | `{"status": "success"}` |
| `POST`| `/api/hostel/settings` | Update curfew hours (Start & End time). | `{"start_time": "17:00", "end_time": "19:30"}` | `{"status": "updated"}` |

---

## 4. UI Component Hierarchy
- `HostelDashboard`: Main container view.
  - `HeaderBanner`: System timestamp, Warden profile, quick stats summary badges.
  - `DualStreamGrid`:
    - `CameraWidget(id="CAM_01_ENTRY", label="Entry Gate")`: Canvas bounding box overlay.
    - `CameraWidget(id="CAM_02_EXIT", label="Exit Gate")`: Canvas bounding box overlay.
  - `OverdueAlertPanel`: Highlighting overdue students past 7:30 PM with single-click parent call / resolve buttons.
  - `MovementLogsTable`: Infinite scrolling or auto-refreshing table showing real-time `IN` and `OUT` events.
