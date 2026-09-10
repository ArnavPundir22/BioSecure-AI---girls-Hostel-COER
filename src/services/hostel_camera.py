"""
Hostel Resilient Dual-Gate Camera Streaming & Face Recognition Engine.

Features:
1. Concurrent IN Gate (Channel 1 -> CAM_01_ENTRY -> logs 'IN') and
   OUT Gate (Channel 2 -> CAM_02_EXIT -> logs 'OUT') stream workers.
2. Direct integration with src.utils.hostel_state (HostelMovementEngine)
   for 15-second anti-bounce cooldown, verified state transitions, and debouncing.
3. Zero-Crash Resilience: handles network dropouts, bad credentials, and DVR
   reboots via non-blocking reconnection loops and automatic fallback hierarchy:
   Primary RTSP -> USB webcam -> dynamic synthetic diagnostic frame with live clock.
4. Live connection prober test_camera_connection(settings) measuring latency,
   resolution, FPS, and returning base64 JPEG thumbnail with guaranteed resource release.
5. Hot configuration reloading without restarting Flask/Gunicorn or dropping active streams.
"""

import base64
import copy
import cv2
import fcntl
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

import numpy as np

from src import config
from src.utils import hostel_db, hostel_state
from src.utils.face import model as face_model, normalize_embedding
from src.utils.face_cache import (
    ensure_cache_initialized,
    match_faces_batch,
    reload_face_cache,
)

logger = logging.getLogger(__name__)

# Global AI inference lock to prevent CPU core contention between IN and OUT workers
_ai_inference_lock = threading.Lock()

# IPC Signal & Lock File Paths
LOCK_PATH = "/tmp/hostel_camera_device.lock"
CAMERA_RELOAD_SIGNAL_PATH = "/tmp/hostel_camera_reload.signal"


def _mask_rtsp_url(url: Any) -> str:
    """Mask credentials in RTSP URL for secure logging and telemetry."""
    if url is None:
        return ""
    url_str = str(url).strip()
    if not url_str:
        return ""
    if url_str == "0":
        return "0"

    # Match URLs with credentials: scheme://[username]:[password]@[host:port][/path]
    # Uses greedy match on password up to the last '@' before host/port to preserve host/path
    match = re.match(r"^([a-zA-Z0-9_+.-]+://[^:@/]*:)(?:.+)@([^/@]+.*)$", url_str)
    if match:
        return f"{match.group(1)}****@{match.group(2)}"

    return url_str


def _resolve_stream_source(settings: Any) -> Union[int, str]:
    """Resolve stream source from settings dict, RTSP string, or integer index."""
    if settings is None:
        return 0

    if isinstance(settings, int):
        return settings

    if isinstance(settings, str):
        cleaned = settings.strip()
        if cleaned.isdigit():
            return int(cleaned)
        return cleaned

    if isinstance(settings, dict):
        url = hostel_db.build_rtsp_url(settings)
        if url.isdigit():
            return int(url)
        return url

    return 0


def _open_capture_with_timeout(
    source: Union[int, str],
    timeout_sec: float = 3.5
) -> Optional[cv2.VideoCapture]:
    """
    Open VideoCapture with strict timeout protection via watchdog thread
    to prevent indefinite C-level network hangs on unreachable RTSP hosts.
    """
    if isinstance(source, str) and source.startswith("rtsp://"):
        # TCP transport prevents UDP packet loss; timeout in microseconds
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|timeout;3000000|stimeout;3000000"
        )

    cap_holder: List[Optional[cv2.VideoCapture]] = [None]
    exception_holder: List[Optional[Exception]] = [None]

    def _open_target():
        try:
            cap = cv2.VideoCapture(source)
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout_sec * 1000))
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout_sec * 1000))
            cap_holder[0] = cap
        except Exception as e:
            exception_holder[0] = e

    t = threading.Thread(target=_open_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        logger.warning(
            f"Watchdog timeout ({timeout_sec}s) attempting to open stream: "
            f"{_mask_rtsp_url(str(source))}"
        )
        return None

    if exception_holder[0] is not None:
        logger.warning(f"Exception opening stream source: {exception_holder[0]}")
        return None

    return cap_holder[0]


def _create_synthetic_diagnostic_frame(
    role: str,
    status_text: str = "STREAM CONNECTING",
    detail_text: str = "Awaiting video frames...",
    latency_ms: Optional[float] = None
) -> bytes:
    """
    Generate dynamic synthetic diagnostic frame (640x360) matching dark glassmorphism design.
    Provides live UTC clock, role badge, status indicator, and diagnostic detail.
    """
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:] = (30, 16, 10)  # Dark slate background #0f172a (BGR: 26, 16, 10 -> (30, 16, 10))

    # Top header bar
    cv2.rectangle(img, (0, 0), (640, 32), (15, 23, 42), -1)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    role_title = f"BIOSECURE AI — CCTV [{role.upper()} GATE]"
    cv2.putText(
        img,
        f"{role_title} (DIAGNOSTIC)",
        (12, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.44,
        (226, 232, 240),
        1,
        cv2.LINE_AA
    )
    cv2.putText(
        img,
        timestamp_str,
        (440, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        (148, 163, 184),
        1,
        cv2.LINE_AA
    )

    # Status indicator pill
    is_online = any(k in status_text.upper() for k in ("CONNECTED", "ONLINE"))
    is_reconnecting = any(k in status_text.upper() for k in ("RECONNECT", "WAIT", "STANDBY", "INITIALIZ"))

    if is_online:
        pill_color = (16, 185, 129)   # Emerald
    elif is_reconnecting:
        pill_color = (0, 165, 255)    # Amber
    else:
        pill_color = (68, 68, 239)    # Crimson

    cv2.rectangle(img, (36, 60), (604, 270), (22, 30, 48), -1)
    cv2.rectangle(img, (36, 60), (604, 270), (51, 65, 85), 1)

    # Status Pill
    cv2.rectangle(img, (56, 85), (260, 120), pill_color, -1)
    cv2.putText(
        img,
        status_text[:22],
        (66, 108),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 255),
        2,
        cv2.LINE_AA
    )

    # Detail text lines
    cv2.putText(
        img,
        detail_text[:56],
        (56, 160),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        (226, 232, 240),
        1,
        cv2.LINE_AA
    )

    if latency_ms is not None:
        latency_str = f"Probe Latency: {latency_ms:.1f} ms"
        cv2.putText(
            img,
            latency_str,
            (56, 195),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (148, 163, 184),
            1,
            cv2.LINE_AA
        )

    engine_str = "Biometric Face Recognition Engine Active | Auto-Fallback Engaged"
    cv2.putText(
        img,
        engine_str,
        (56, 240),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (100, 116, 139),
        1,
        cv2.LINE_AA
    )

    # Bottom footer
    cv2.rectangle(img, (0, 332), (640, 360), (15, 23, 42), -1)
    footer_text = f"Role: {role.upper()} | Cooldown: 15s | Zero-Crash Watchdog Active"
    cv2.putText(
        img,
        footer_text,
        (12, 351),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        (148, 163, 184),
        1,
        cv2.LINE_AA
    )

    ret, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    return buf.tobytes() if ret else b""


_placeholder_bytes = _create_synthetic_diagnostic_frame(
    "IN", "HOSTEL CAMERA INITIALIZING", "Recognition engine ready. Awaiting camera feed..."
)


def test_camera_connection(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Test camera RTSP or webcam connection on-demand, capture a test frame,
    measure resolution, FPS, latency, generate a base64 thumbnail,
    and cleanly release VideoCapture without resource leaks.
    """
    start_time = time.perf_counter()
    if not settings or not isinstance(settings, dict):
        return {
            "success": False,
            "status": "FAILED",
            "error": "Invalid camera configuration",
            "latency_ms": 0.0,
            "url_tested": "",
        }

    vendor = str(settings.get("vendor") or "").strip()
    custom_url = str(settings.get("custom_rtsp_url") or "").strip()
    has_webcam = (
        any(k in vendor.lower() for k in ("usb", "webcam", "local", "camera index"))
        or "webcam" in settings
    )
    is_valid_vendor = bool(vendor)
    is_valid_rtsp = bool(
        custom_url
        and (
            custom_url.lower().startswith("rtsp://")
            or custom_url.lower().startswith("rtsps://")
        )
    )

    if not is_valid_vendor and not is_valid_rtsp and not has_webcam:
        return {
            "success": False,
            "status": "FAILED",
            "error": "Invalid camera configuration",
            "latency_ms": 0.0,
            "url_tested": "",
        }

    cap = None
    try:
        source = _resolve_stream_source(settings)
        masked_source = _mask_rtsp_url(str(source))

        cap = _open_capture_with_timeout(source, timeout_sec=3.5)
        if cap is None or not cap.isOpened():
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 1)
            return {
                "success": False,
                "status": "CONNECTION_FAILED",
                "error": "Could not connect to camera stream. Check IP, port, or network reachability.",
                "latency_ms": elapsed_ms,
                "url_tested": masked_source,
            }

        ret, frame = cap.read()
        if not ret or frame is None:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 1)
            return {
                "success": False,
                "status": "FRAME_READ_FAILED",
                "error": "Connected to stream, but failed to retrieve video frame.",
                "latency_ms": elapsed_ms,
                "url_tested": masked_source,
            }

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 1)
        h, w = frame.shape[:2]
        fps_val = cap.get(cv2.CAP_PROP_FPS)
        fps = (
            round(float(fps_val), 1)
            if (fps_val and fps_val > 0 and not np.isnan(fps_val))
            else 25.0
        )

        scale = min(1.0, 640.0 / float(w))
        thumb = cv2.resize(frame, (int(w * scale), int(h * scale)))
        ret_enc, buf = cv2.imencode(
            ".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 75]
        )

        preview_data_url = ""
        if ret_enc:
            b64_str = base64.b64encode(buf).decode("ascii")
            preview_data_url = f"data:image/jpeg;base64,{b64_str}"

        return {
            "success": True,
            "status": "CONNECTED",
            "resolution": f"{w}x{h}",
            "fps": fps,
            "latency_ms": elapsed_ms,
            "preview_image": preview_data_url,
            "url_tested": masked_source,
        }
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 1)
        logger.error(f"Error testing camera connection: {e}")
        return {
            "success": False,
            "status": "ERROR",
            "error": str(e),
            "latency_ms": elapsed_ms,
        }
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


class CameraStreamWorker:
    """
    Dedicated worker managing video capture, zero-crash resilience,
    and asynchronous AI recognition for a single gate role ('IN' or 'OUT').
    """

    def __init__(self, role: str, initial_config: Optional[Dict[str, Any]] = None):
        self.role = role.upper()
        self.camera_id = "CAM_01_ENTRY" if self.role == "IN" else "CAM_02_EXIT"
        self.direction = "IN" if self.role == "IN" else "OUT"
        self.config = initial_config or {}

        self.running = False
        self.reconfigure_requested = False
        self.new_config: Optional[Dict[str, Any]] = None

        self.status = "INITIALIZING"
        self.status_detail = "Waiting to connect..."
        self.cap: Optional[cv2.VideoCapture] = None
        self.current_source: Optional[Any] = None

        self.capture_thread: Optional[threading.Thread] = None
        self.ai_thread: Optional[threading.Thread] = None

        # Thread-safe frame buffers
        self.frame_lock = threading.Lock()
        self.latest_display_frame: Optional[np.ndarray] = None
        self.latest_small_frame: Optional[np.ndarray] = None
        self.latest_scale_x: float = 1.0
        self.latest_scale_y: float = 1.0
        self.cached_overlays: List[Dict[str, Any]] = []

        self.jpeg_lock = threading.Lock()
        self.latest_jpeg_bytes: Optional[bytes] = None

        # Recognition streak tracking
        self.detection_streaks: Dict[str, int] = {}

        # Dual-Tier Thresholds
        self.HIGH_CONFIDENCE_THRESHOLD = 0.36
        self.MIN_MATCH_THRESHOLD = 0.28

        # Disk frame paths for inter-process reading
        self.frame_path = f"/tmp/hostel_live_frame_{self.role.lower()}.jpg"
        self.legacy_frame_path = (
            "/tmp/hostel_live_frame.jpg" if self.role == "IN" else None
        )

    def start(self):
        """Start capture and AI worker threads."""
        if self.running:
            return
        self.running = True
        self.capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name=f"CapWorker-{self.role}"
        )
        self.capture_thread.start()

        self.ai_thread = threading.Thread(
            target=self._ai_worker_loop, daemon=True, name=f"AIWorker-{self.role}"
        )
        self.ai_thread.start()
        logger.info(f"CameraStreamWorker started for {self.role} Gate ({self.camera_id}).")

    def stop(self):
        """Stop worker threads and release camera hardware."""
        self.running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
        if self.ai_thread and self.ai_thread.is_alive():
            self.ai_thread.join(timeout=2.0)
        if self.cap and self.cap.isOpened():
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        logger.info(f"CameraStreamWorker stopped for {self.role} Gate.")

    def reconfigure(self, new_settings: Dict[str, Any]):
        """Request non-blocking reconfiguration with new settings."""
        self.new_config = copy.deepcopy(new_settings)
        self.reconfigure_requested = True
        logger.info(f"Reconfiguration requested for {self.role} Gate worker.")

    def get_latest_jpeg(self) -> bytes:
        """Return latest encoded JPEG frame bytes or fallback with live timestamp."""
        # When worker is not ONLINE (e.g. RECONNECTING backoff sleep, CONNECTING, etc.),
        # dynamically generate a fresh synthetic frame so the live clock advances smoothly.
        if self.status != "ONLINE":
            return _create_synthetic_diagnostic_frame(
                self.role, self.status, self.status_detail
            )

        with self.jpeg_lock:
            if self.latest_jpeg_bytes:
                return self.latest_jpeg_bytes

        if os.path.exists(self.frame_path):
            try:
                with open(self.frame_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        if self.legacy_frame_path and os.path.exists(self.legacy_frame_path):
            try:
                with open(self.legacy_frame_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        return _create_synthetic_diagnostic_frame(
            self.role, self.status, self.status_detail
        )

    def get_frame(self) -> bytes:
        """Return current frame bytes with live timestamp."""
        return self.get_latest_jpeg()

    def generate_mjpeg_stream(self) -> Generator[bytes, None, None]:
        """Generate multipart MJPEG video stream."""
        while self.running:
            frame_bytes = self.get_latest_jpeg()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(0.033)

    def _capture_loop(self):
        """High-FPS video capture loop with zero-crash fallback hierarchy."""
        reconnect_attempts = 0
        fallback_tier = 1

        while self.running:
            # Handle hot reconfiguration request
            if self.reconfigure_requested and self.new_config is not None:
                logger.info(f"Applying hot reconfiguration for {self.role} Gate.")
                self.config = self.new_config
                self.new_config = None
                self.reconfigure_requested = False
                reconnect_attempts = 0
                fallback_tier = 1
                if self.cap and self.cap.isOpened():
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                self.cap = None

            # Check if camera stream is enabled
            if not self.config.get("enabled", True):
                self.status = "DISABLED"
                self.status_detail = f"{self.role} Gate stream disabled in settings"
                synth = _create_synthetic_diagnostic_frame(
                    self.role, self.status, self.status_detail
                )
                self._update_jpeg(synth)
                time.sleep(1.0)
                continue

            # Open stream if not currently open
            if self.cap is None or not self.cap.isOpened():
                if fallback_tier == 1:
                    target_source = _resolve_stream_source(self.config)
                    self.status = "CONNECTING"
                    self.status_detail = f"Connecting to {_mask_rtsp_url(str(target_source))}"
                elif fallback_tier == 2:
                    target_source = 0 if self.role == "IN" else 1
                    self.status = "FALLBACK_WEBCAM"
                    self.status_detail = f"Falling back to local camera index {target_source}"
                else:
                    self.status = "RECONNECTING"
                    self.status_detail = (
                        f"Stream offline (attempt #{reconnect_attempts}). Retrying..."
                    )
                    synth = _create_synthetic_diagnostic_frame(
                        self.role, self.status, self.status_detail
                    )
                    self._update_jpeg(synth)
                    backoff = min(30.0, 2.0 * (2 ** min(reconnect_attempts, 4))) + random.uniform(0.0, 0.5)
                    self._sleep_interruptible(backoff)
                    fallback_tier = 1
                    reconnect_attempts += 1
                    continue

                self.current_source = target_source
                self.cap = _open_capture_with_timeout(target_source, timeout_sec=3.0)

                if self.cap is None or not self.cap.isOpened():
                    reconnect_attempts += 1
                    fallback_tier += 1
                    time.sleep(0.5)
                    continue

                reconnect_attempts = 0
                self.status = "ONLINE"
                self.status_detail = "Live feed active"

            # Read frame from stream
            ret, frame = self.cap.read()
            if not ret or frame is None:
                reconnect_attempts += 1
                if reconnect_attempts >= 3:
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    fallback_tier += 1
                time.sleep(0.03)
                continue

            reconnect_attempts = 0

            # Scale for display (800w) and detection (380w)
            h, w = frame.shape[:2]
            target_w = 800
            scale_disp = target_w / float(w)
            target_h = int(h * scale_disp)
            display_frame = cv2.resize(frame, (target_w, target_h))

            det_w = 380
            scale_det_x = target_w / float(det_w)
            det_h = int(target_h / scale_det_x)
            scale_det_y = target_h / float(det_h)
            small_frame = cv2.resize(display_frame, (det_w, det_h))

            # Share detection frame with AI worker thread
            with self.frame_lock:
                self.latest_small_frame = small_frame
                self.latest_scale_x = scale_det_x
                self.latest_scale_y = scale_det_y
                current_overlays = list(self.cached_overlays)

            # Render overlay annotations
            for item in current_overlays:
                x1, y1, x2, y2 = item["bbox"]
                box_color = item["color"]
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), box_color, 2)
                cv2.rectangle(
                    display_frame, (x1, max(0, y1 - 40)), (x2, y1), box_color, -1
                )
                cv2.putText(
                    display_frame,
                    item["label"],
                    (x1 + 6, max(15, y1 - 22)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                if item.get("sub_label"):
                    cv2.putText(
                        display_frame,
                        item["sub_label"],
                        (x1 + 6, max(30, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )

            # Top live telemetry bar
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.rectangle(
                display_frame, (0, 0), (display_frame.shape[1], 28), (10, 16, 30), -1
            )
            role_badge = f"BIOSECURE AI — CCTV {self.role} GATE ({self.camera_id})"
            cv2.putText(
                display_frame,
                f"{role_badge} | {timestamp_str}",
                (12, 19),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (226, 232, 240),
                1,
                cv2.LINE_AA,
            )

            # Encode to JPEG and update caches
            ret_enc, buffer = cv2.imencode(
                ".jpg", display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75]
            )
            if ret_enc:
                encoded_bytes = buffer.tobytes()
                self._update_jpeg(encoded_bytes)

            time.sleep(0.015)

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _ai_worker_loop(self):
        """Asynchronous AI face detection and recognition thread."""
        logger.info(f"AI Recognition Worker active for {self.role} Gate.")
        while self.running:
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
                # Use global lock to prevent thread contention during ONNX inference
                with _ai_inference_lock:
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
                        matches = match_faces_batch(
                            embeddings, match_threshold=self.MIN_MATCH_THRESHOLD
                        )

                        for face, match in zip(valid_faces, matches):
                            s_bbox = face.bbox.astype(float)
                            x1 = int(s_bbox[0] * scale_det_x)
                            y1 = int(s_bbox[1] * scale_det_y)
                            x2 = int(s_bbox[2] * scale_det_x)
                            y2 = int(s_bbox[3] * scale_det_y)

                            if match:
                                student_id = match["id"]
                                name = match["name"]
                                sim = match["similarity"]
                                roll = match.get("roll_number") or ""
                                room = match.get("room_number") or ""

                                streak = self.detection_streaks.get(student_id, 0) + 1
                                self.detection_streaks[student_id] = streak
                                current_frame_matched_ids.add(student_id)

                                is_verified = (
                                    sim >= self.HIGH_CONFIDENCE_THRESHOLD
                                ) or (streak >= 2)

                                if is_verified:
                                    student_info = (
                                        hostel_db.get_student_by_id(student_id) or {}
                                    )
                                    if not roll:
                                        roll = student_info.get("roll_number", "")
                                    if not room:
                                        room = student_info.get("room_number", "")

                                    # Process student detection via state machine
                                    target_dir = hostel_state.process_student_detection(
                                        student_id=student_id,
                                        camera_id=self.camera_id,
                                        student_info=student_info,
                                    )

                                    current_status = student_info.get(
                                        "current_status", self.direction
                                    )
                                    if target_dir:
                                        current_status = target_dir

                                    box_color = (
                                        (129, 185, 16)
                                        if current_status == "IN"
                                        else (11, 158, 245)
                                    )
                                    new_overlays.append({
                                        "bbox": (x1, y1, x2, y2),
                                        "color": box_color,
                                        "label": f"{name} [{current_status}] - {sim*100:.0f}%",
                                        "sub_label": f"Roll: {roll} | Room: {room}",
                                    })
                                else:
                                    new_overlays.append({
                                        "bbox": (x1, y1, x2, y2),
                                        "color": (241, 102, 99),
                                        "label": f"VERIFYING: {name} ({sim*100:.0f}%)",
                                        "sub_label": "Hold still for verification...",
                                    })
                            else:
                                new_overlays.append({
                                    "bbox": (x1, y1, x2, y2),
                                    "color": (68, 68, 239),
                                    "label": "UNKNOWN VISITOR",
                                    "sub_label": "",
                                })
            except Exception as e:
                logger.error(f"Error in {self.role} Gate AI worker: {e}")

            for sid in list(self.detection_streaks.keys()):
                if sid not in current_frame_matched_ids:
                    self.detection_streaks[sid] = max(
                        0, self.detection_streaks[sid] - 1
                    )

            with self.frame_lock:
                self.cached_overlays = new_overlays

            time.sleep(0.02)

    def _update_jpeg(self, encoded_bytes: bytes):
        """Update in-memory buffer and write atomic image file to disk."""
        with self.jpeg_lock:
            self.latest_jpeg_bytes = encoded_bytes

        try:
            tmp = self.frame_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(encoded_bytes)
            os.replace(tmp, self.frame_path)

            if self.legacy_frame_path:
                tmp_leg = self.legacy_frame_path + ".tmp"
                with open(tmp_leg, "wb") as f:
                    f.write(encoded_bytes)
                os.replace(tmp_leg, self.legacy_frame_path)
        except Exception:
            pass

    def _sleep_interruptible(self, duration: float):
        """Sleep in small 0.1s increments to respond promptly to stops or reconfigures."""
        end_time = time.time() + duration
        while self.running and not self.reconfigure_requested and time.time() < end_time:
            time.sleep(0.1)


class HostelCameraManager:
    """
    Singleton coordinator managing concurrent IN and OUT CameraStreamWorkers.
    Handles process-level locking for Gunicorn, database configuration hot-reloading,
    and MJPEG stream routing.
    """

    _instance: Optional["HostelCameraManager"] = None
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
        self.workers: Dict[str, CameraStreamWorker] = {}
        self.running = False
        self.is_primary = False
        self.lock_file = None
        self.ipc_thread: Optional[threading.Thread] = None
        self.last_signal_mtime: float = 0.0

    def start(self, camera_index: int = 0):
        """Acquire process lock and start concurrent IN and OUT workers."""
        if self.running:
            return
        self.running = True

        try:
            ensure_cache_initialized()
        except Exception as e:
            logger.warning(f"Initial face cache load notice: {e}")

        # Attempt to acquire device lock for multi-worker Gunicorn environments
        try:
            self.lock_file = open(LOCK_PATH, "w")
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.is_primary = True
            logger.info(
                f"Worker PID {os.getpid()} acquired camera hardware lock ({LOCK_PATH})."
            )
        except (IOError, OSError):
            self.is_primary = False
            logger.info(
                f"Worker PID {os.getpid()} running in client mode (hardware locked by primary worker)."
            )

        if self.is_primary:
            settings_in = hostel_db.get_camera_settings("IN") or {}
            settings_out = hostel_db.get_camera_settings("OUT") or {}

            self.workers["IN"] = CameraStreamWorker("IN", settings_in)
            self.workers["OUT"] = CameraStreamWorker("OUT", settings_out)

            self.workers["IN"].start()
            self.workers["OUT"].start()

        # Start IPC watcher thread in both primary and client modes
        self.ipc_thread = threading.Thread(
            target=self._ipc_watcher_loop, daemon=True, name="CameraIPCWatcher"
        )
        self.ipc_thread.start()
        logger.info("HostelCameraManager started.")

    def stop(self):
        """Stop all workers and release hardware lock."""
        self.running = False
        for worker in self.workers.values():
            worker.stop()
        self.workers.clear()

        if self.lock_file:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_UN)
                self.lock_file.close()
            except Exception:
                pass
            self.lock_file = None
        logger.info("HostelCameraManager stopped.")

    def reload_camera_configurations(self) -> Dict[str, bool]:
        """Fetch updated DB settings and hot-reload worker configurations."""
        results = {"IN": False, "OUT": False}
        if not self.is_primary:
            logger.info("Non-primary worker received reload; touching IPC signal.")
            hostel_db.trigger_camera_reload_signal()
            return {"IN": True, "OUT": True}

        try:
            settings_in = hostel_db.get_camera_settings("IN") or {}
            settings_out = hostel_db.get_camera_settings("OUT") or {}

            if "IN" in self.workers:
                self.workers["IN"].reconfigure(settings_in)
                results["IN"] = True
            if "OUT" in self.workers:
                self.workers["OUT"].reconfigure(settings_out)
                results["OUT"] = True

            logger.info("Hot-reloaded camera configurations for IN and OUT gates.")
        except Exception as e:
            logger.error(f"Failed to reload camera configurations: {e}")

        return results

    def get_latest_jpeg(self, role: str = "IN") -> bytes:
        """Return latest JPEG bytes for specified role, falling back to disk or synthetic frame."""
        role_norm = role.strip().upper() if role else "IN"
        if role_norm not in ("IN", "OUT"):
            role_norm = "IN"

        if self.is_primary and role_norm in self.workers:
            return self.workers[role_norm].get_latest_jpeg()

        # Client mode (or primary without active worker): read from disk
        target_path = f"/tmp/hostel_live_frame_{role_norm.lower()}.jpg"
        if os.path.exists(target_path):
            try:
                with open(target_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        if role_norm == "IN" and os.path.exists("/tmp/hostel_live_frame.jpg"):
            try:
                with open("/tmp/hostel_live_frame.jpg", "rb") as f:
                    return f.read()
            except Exception:
                pass

        return _create_synthetic_diagnostic_frame(
            role_norm, "AWAITING FEED", "Camera worker starting up..."
        )

    def get_frame(self, role: str = "IN") -> bytes:
        """Return current frame bytes for role."""
        return self.get_latest_jpeg(role=role)

    def generate_mjpeg_stream(
        self, role: str = "IN"
    ) -> Generator[bytes, None, None]:
        """Generate multipart MJPEG video stream for specified role."""
        role_norm = role.strip().upper() if role else "IN"
        if role_norm not in ("IN", "OUT"):
            role_norm = "IN"

        if self.is_primary and role_norm in self.workers:
            yield from self.workers[role_norm].generate_mjpeg_stream()
            return

        # Fallback generator for client processes
        while self.running:
            frame_bytes = self.get_latest_jpeg(role=role_norm)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(0.033)

    def _ipc_watcher_loop(self):
        """Monitor IPC signal file for cross-process hot configuration reload notifications."""
        while self.running:
            try:
                if os.path.exists(CAMERA_RELOAD_SIGNAL_PATH):
                    mtime = os.path.getmtime(CAMERA_RELOAD_SIGNAL_PATH)
                    if mtime > self.last_signal_mtime:
                        self.last_signal_mtime = mtime
                        if self.is_primary:
                            logger.info(
                                "IPC reload signal detected. Reloading worker configs."
                            )
                            self.reload_camera_configurations()
            except Exception as e:
                logger.debug(f"IPC watcher check notice: {e}")
            time.sleep(1.0)


_camera_manager = HostelCameraManager()


def get_camera_manager() -> HostelCameraManager:
    return _camera_manager


def start_hostel_camera(camera_index: int = 0) -> HostelCameraManager:
    """Initialize and start the camera manager background coordinator."""
    mgr = get_camera_manager()
    if not mgr.running:
        mgr.start(camera_index=camera_index)
    return mgr
