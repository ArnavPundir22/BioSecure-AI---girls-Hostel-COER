# 🔌 API Reference Manual

This manual documents the REST endpoints, MJPEG live streaming interfaces, expected payloads, and responses for **BioSecure AI — Girls Hostel Management Platform**.

---

## 📹 Video Feed & Stream Endpoints

### `GET /hostel/video_feed`
Serves a high-FPS persistent **MJPEG multipart video stream** (`multipart/x-mixed-replace`) from the host computer's webcam with real-time face recognition bounding boxes and IN/OUT status overlays.
- **MIME Type**: `multipart/x-mixed-replace; boundary=frame`
- **Output**: Continuous JPEG frames streamed at **30 FPS**.
- **Usage**: Used directly in front-end `<img>` tags (`<img src="/hostel/video_feed" />`).

### `GET /hostel/video_frame`
Returns a single latest JPEG snapshot from the host camera.
- **Query Parameter**: `cam` or `camera_id` (e.g., `CAM_01` or `CAM_02`).
- **MIME Type**: `image/jpeg`
- **Output**: Single encoded JPEG frame buffer.

---

## 📷 Face Processing & Attendance Endpoints

### `POST /process_frame`
Processes a single camera snapshot payload for real-time face recognition and attendance logging.
- **Request Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "image": "data:image/jpeg;base64,/9j/4AAQSkZJR..."
  }
  ```
- **Success Response (200 OK - JSON)**:
  ```json
  {
    "id": "STU_1002",
    "name": "Ananya Sharma",
    "roll_number": "CSE-2026-012",
    "program": "B.Tech",
    "branch": "Computer Science",
    "last": "2026-09-09 19:15:00",
    "message": "Matched"
  }
  ```

---

## 🔐 Authentication & Session Endpoints

### `POST /login`
Authenticates a warden or administrative user.
- **Request Headers**: `Content-Type: application/x-www-form-urlencoded`
- **Request Body**: `email`, `password`
- **Success Response**: Redirects to dashboard and establishes session cookie.

### `GET /logout`
Terminates the active session.
- **Success Response**: Redirects to `/login`.

---

## 👨‍💼 Hostel Warden & Admin Endpoints

### `GET /hostel/`
Renders the primary **Warden Control Center Dashboard** with live entry/exit gate camera streams, active Movement Logs, and Curfew summary widgets.

### `GET /hostel/logs`
Retrieves paginated movement history logs (Entry & Exit timestamps, Student IDs, Camera IDs, Status).

### `GET /hostel/curfew`
Renders curfew management interface and active curfew violation logs.

### `GET /admin/drift`
Renders the **Biometric Embedding Drift Management Dashboard**, displaying EWMA template aging metrics (`HEALTHY`, `WARNING`, `CRITICAL`, `ALERT`).

### `POST /student/reset_drift/<student_id>`
Resets a student's EWMA drift score to `0.0` upon template re-enrollment.

---

## 👥 Student Directory & Guided Enrollment Endpoints

### `POST /submit_student`
Registers a new student profile, saves their portrait photo to `known_faces/`, and generates their 512D ArcFace face embedding.
- **Request Headers**: `Content-Type: multipart/form-data`
- **Request Body**:
  - `name` (string): Full Name
  - `roll_number` (string): Roll Number
  - `room_number` (string): Hostel Room Number
  - `branch` (string): Academic Branch
  - `photo` (file binary): Enrollment Photo
- **Success Response**: Redirects to `/students`.

---

## ⚠️ Error Handling & Status Codes

* **JSON API Responses** (`Accept: application/json`): Returns structured error payloads (`{"error": "Description"}`).
* **HTML UI Requests**: Renders custom glassmorphic error templates (`error_404.html`, `error_403.html`, `error_500.html`).
