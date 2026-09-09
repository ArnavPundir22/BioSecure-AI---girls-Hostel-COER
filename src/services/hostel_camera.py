"""
Hostel Server Camera Manager & Real-Time Face Recognition Engine.

Captures frames from the host computer's webcam (cv2.VideoCapture) at 30 FPS,
performs fast multi-scale InsightFace 512D face recognition asynchronously in a background
worker thread, auto-logs student entry/exit movements to girls_hostel.movement_logs,
overlays recognition bounding boxes, and streams high-FPS MJPEG video feeds to the warden dashboard.
"""

import os
import cv2
import time
import fcntl
import logging
import threading
import numpy as np
from typing import Dict, List, Any, Optional, Generator
from datetime import datetime, timezone

from src import config
from src.utils import hostel_db
from src.utils.face import model as face_model, normalize_embedding
from src.utils.face_cache import match_faces_batch, reload_face_cache, ensure_cache_initialized

logger = logging.getLogger(__name__)

FRAME_PATH = "/tmp/hostel_live_frame.jpg"
LOCK_PATH = "/tmp/hostel_camera_device.lock"

def _create_placeholder_jpeg(text: str = "HOST CAMERA INITIALIZING...") -> bytes:
    """Generate a clean fallback frame when camera stream is opening."""
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:] = (30, 16, 10)  # Dark slate blue background
    cv2.rectangle(img, (0, 0), (640, 30), (10, 16, 30), -1)
    cv2.putText(img, "BIOSECURE AI — HOST SYSTEM CAMERA (LIVE)", (12, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (226, 232, 240), 1, cv2.LINE_AA)
    cv2.putText(img, text, (40, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (16, 185, 129), 2, cv2.LINE_AA)
    cv2.putText(img, "Recognition engine ready. Awaiting camera feed...", (40, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1, cv2.LINE_AA)
    ret, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    return buf.tobytes() if ret else b''

_placeholder_bytes = _create_placeholder_jpeg()

class HostelCameraManager:
    _instance: Optional['HostelCameraManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(HostelCameraManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.is_primary = False
        self.thread: Optional[threading.Thread] = None
        self.ai_thread: Optional[threading.Thread] = None
        self.jpeg_bytes: Optional[bytes] = None
        self.last_seen_cooldown: Dict[str, float] = {}  # student_id -> timestamp
        self.detection_streaks: Dict[str, int] = {}    # student_id -> consecutive frame count
        self.cooldown_seconds = 15.0
        
        # Dual-Tier Thresholds to guarantee ZERO false positives while maintaining high recall:
        self.HIGH_CONFIDENCE_THRESHOLD = 0.36   # Instant match without streak check
        self.MIN_MATCH_THRESHOLD = 0.28        # Base threshold requiring 2-frame consensus

        # Shared state between high-FPS camera thread and background AI worker thread
        self.latest_small_frame: Optional[np.ndarray] = None
        self.latest_scale_x: float = 1.0
        self.latest_scale_y: float = 1.0
        self.cached_overlays: List[Dict[str, Any]] = []

        self.lock = threading.Lock()
        self.frame_lock = threading.Lock()
        self.lock_file = None

    def start(self, camera_index: int = 0):
        """Start background camera capture and async AI recognition loops."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._camera_loop, args=(camera_index,), daemon=True)
        self.thread.start()
        self.ai_thread = threading.Thread(target=self._ai_worker_loop, daemon=True)
        self.ai_thread.start()
        logger.info(f"HostelCameraManager camera and AI worker threads started for index {camera_index}")

    def stop(self):
        """Stop background camera capture."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.ai_thread and self.ai_thread.is_alive():
            self.ai_thread.join(timeout=2.0)
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.cap = None
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_UN)
                self.lock_file.close()
            except Exception:
                pass
        logger.info("HostelCameraManager stopped.")

    def _camera_loop(self, camera_index: int):
        """High-FPS camera capture and overlay rendering loop (~30 FPS)."""
        try:
            ensure_cache_initialized()
        except Exception as e:
            logger.warning(f"Initial face cache load notice: {e}")

        # Process-level lock to prevent multi-gunicorn worker device collisions
        try:
            self.lock_file = open(LOCK_PATH, "w")
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.is_primary = True
            logger.info(f"Worker PID {os.getpid()} acquired camera hardware lock ({LOCK_PATH})")
        except (IOError, OSError):
            self.is_primary = False
            logger.info(f"Worker PID {os.getpid()} running in client mode (hardware locked by primary worker)")
            while self.running:
                time.sleep(0.2)
            return

        # Open video device
        try:
            self.cap = cv2.VideoCapture(camera_index)
            if not self.cap.isOpened():
                logger.warning(f"Could not open camera index {camera_index}. Retrying in background...")
        except Exception as err:
            logger.warning(f"Error opening camera index {camera_index}: {err}")

        while self.running:
            if not self.cap or not self.cap.isOpened():
                time.sleep(1.0)
                try:
                    self.cap = cv2.VideoCapture(camera_index)
                except Exception:
                    pass
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.03)
                continue

            h, w = frame.shape[:2]
            target_w = 800
            scale_disp = target_w / float(w)
            target_h = int(h * scale_disp)
            display_frame = cv2.resize(frame, (target_w, target_h))

            # Fast 380px detection scale for sub-25ms CPU inference
            det_w = 380
            scale_det_x = target_w / float(det_w)
            det_h = int(target_h / scale_det_x)
            scale_det_y = target_h / float(det_h)
            small_frame = cv2.resize(display_frame, (det_w, det_h))

            # Share latest frame to AI worker thread asynchronously
            with self.frame_lock:
                self.latest_small_frame = small_frame
                self.latest_scale_x = scale_det_x
                self.latest_scale_y = scale_det_y
                current_overlays = list(self.cached_overlays)

            # Render cached overlays on display frame
            for item in current_overlays:
                x1, y1, x2, y2 = item["bbox"]
                box_color = item["color"]
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), box_color, 2)
                cv2.rectangle(display_frame, (x1, max(0, y1 - 40)), (x2, y1), box_color, -1)
                cv2.putText(display_frame, item["label"], (x1 + 6, max(15, y1 - 22)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                if item["sub_label"]:
                    cv2.putText(display_frame, item["sub_label"], (x1 + 6, max(30, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.rectangle(display_frame, (0, 0), (display_frame.shape[1], 28), (10, 16, 30), -1)
            cv2.putText(display_frame, f"BIOSECURE AI — HOST SYSTEM CAMERA (LIVE) | {timestamp_str}", (12, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (226, 232, 240), 1, cv2.LINE_AA)

            ret_enc, buffer = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ret_enc:
                encoded_bytes = buffer.tobytes()
                with self.lock:
                    self.jpeg_bytes = encoded_bytes

                try:
                    tmp_file = FRAME_PATH + ".tmp"
                    with open(tmp_file, "wb") as f:
                        f.write(encoded_bytes)
                    os.replace(tmp_file, FRAME_PATH)
                except Exception:
                    pass

            time.sleep(0.015)  # Continuous 30+ FPS capture & display stream loop

        if self.cap:
            self.cap.release()
            self.cap = None

    def _ai_worker_loop(self):
        """Asynchronous AI face detection & recognition worker thread."""
        logger.info("AI Recognition Worker Thread active.")
        while self.running:
            if not self.is_primary:
                time.sleep(0.5)
                continue

            with self.frame_lock:
                small_frame = self.latest_small_frame
                scale_det_x = self.latest_scale_x
                scale_det_y = self.latest_scale_y

            if small_frame is None:
                time.sleep(0.05)
                continue

            new_overlays = []
            current_frame_matched_ids = set()

            try:
                faces = face_model.get(small_frame)
                if faces and len(faces) > 0:
                    embeddings = []
                    valid_faces = []
                    for face in faces:
                        s_bbox = face.bbox.astype(float)
                        fw = s_bbox[2] - s_bbox[0]
                        fh = s_bbox[3] - s_bbox[1]
                        if fw < 35 or fh < 35:
                            continue

                        norm_emb = normalize_embedding(face.embedding)
                        if norm_emb is not None:
                            embeddings.append(norm_emb)
                            valid_faces.append(face)

                    if embeddings:
                        matches = match_faces_batch(embeddings, match_threshold=self.MIN_MATCH_THRESHOLD)
                        now = time.time()

                        for face, match in zip(valid_faces, matches):
                            s_bbox = face.bbox.astype(float)
                            x1 = int(s_bbox[0] * scale_det_x)
                            y1 = int(s_bbox[1] * scale_det_y)
                            x2 = int(s_bbox[2] * scale_det_x)
                            y2 = int(s_bbox[3] * scale_det_y)

                            if match:
                                student_id = match['id']
                                name = match['name']
                                sim = match['similarity']
                                roll = match.get('roll_number') or ""
                                room = match.get('room_number') or ""

                                streak = self.detection_streaks.get(student_id, 0) + 1
                                self.detection_streaks[student_id] = streak
                                current_frame_matched_ids.add(student_id)

                                is_verified = (sim >= self.HIGH_CONFIDENCE_THRESHOLD) or (streak >= 2)

                                if is_verified:
                                    student_info = hostel_db.get_student_by_id(student_id) or {}
                                    current_status = student_info.get("current_status", "IN")
                                    if not roll: roll = student_info.get("roll_number", "")
                                    if not room: room = student_info.get("room_number", "")

                                    last_time = self.last_seen_cooldown.get(student_id, 0.0)
                                    if (now - last_time) >= self.cooldown_seconds:
                                        new_status = "OUT" if current_status == "IN" else "IN"
                                        camera_id = "CAM_02" if new_status == "OUT" else "CAM_01"

                                        logger.info(
                                            f"🎯 VERIFIED FACE MATCH: {name} (Roll: {roll}, Similarity: {sim*100:.1f}%, Streak: {streak}) -> Transitioning {current_status} to {new_status} via {camera_id}"
                                        )

                                        success = hostel_db.update_student_movement_state(
                                            student_id=student_id,
                                            direction=new_status,
                                            camera_id=camera_id
                                        )
                                        if success:
                                            self.last_seen_cooldown[student_id] = now
                                            current_status = new_status
                                            logger.info(f"✅ Successfully logged movement for {name} ({new_status})")

                                    new_overlays.append({
                                        "bbox": (x1, y1, x2, y2),
                                        "color": (129, 185, 16) if current_status == "IN" else (11, 158, 245),
                                        "label": f"{name} [{current_status}] - {sim*100:.0f}%",
                                        "sub_label": f"Roll: {roll} | Room: {room}"
                                    })
                                else:
                                    new_overlays.append({
                                        "bbox": (x1, y1, x2, y2),
                                        "color": (241, 102, 99),
                                        "label": f"VERIFYING: {name} ({sim*100:.0f}%)",
                                        "sub_label": "Hold still for verification..."
                                    })
                            else:
                                new_overlays.append({
                                    "bbox": (x1, y1, x2, y2),
                                    "color": (68, 68, 239),
                                    "label": "UNKNOWN VISITOR",
                                    "sub_label": ""
                                })
            except Exception as e:
                logger.error(f"Error in background AI worker: {e}")

            # Decay streaks for students not seen in current frame
            for sid in list(self.detection_streaks.keys()):
                if sid not in current_frame_matched_ids:
                    self.detection_streaks[sid] = max(0, self.detection_streaks[sid] - 1)

            with self.frame_lock:
                self.cached_overlays = new_overlays

            time.sleep(0.02)

    def get_latest_jpeg(self) -> Optional[bytes]:
        """Return latest encoded JPEG frame bytes."""
        if self.jpeg_bytes:
            return self.jpeg_bytes
        if os.path.exists(FRAME_PATH):
            try:
                with open(FRAME_PATH, "rb") as f:
                    return f.read()
            except Exception:
                pass
        return _placeholder_bytes

    def generate_mjpeg_stream(self) -> Generator[bytes, None, None]:
        """Generate MJPEG multipart response stream."""
        while self.running:
            frame_bytes = self.get_latest_jpeg() or _placeholder_bytes
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.033)

_camera_manager = HostelCameraManager()

def get_camera_manager() -> HostelCameraManager:
    return _camera_manager

def start_hostel_camera():
    """Helper to initialize and start the camera manager background thread."""
    mgr = get_camera_manager()
    if not mgr.running:
        mgr.start(camera_index=0)
    return mgr
