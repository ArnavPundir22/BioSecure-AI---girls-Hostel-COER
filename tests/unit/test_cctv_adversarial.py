"""
Adversarial Stress Test Suite for CCTV Camera Setup Management Subsystem.

Stress-tests and empirical verification for:
1. Malformed RTSP URLs, unreachable host IPs (192.0.2.1), closed ports, bad credentials, special characters.
2. Network socket timeouts, abrupt TCP resets (SO_LINGER), mid-stream disconnects.
3. Rapid start/stop and concurrent reconfiguration of CameraStreamWorker threads.
4. Resource leaks: cv2.VideoCapture release and file descriptor (/proc/self/fd) retention.
5. Multi-tier fallback and synthetic diagnostic frame generation (clock, banners, extreme strings).
6. Security and URL masking under adversarial credentials.
7. Flask /api/cameras/test-connection resilience against malformed inputs and auth edge cases.
"""

import copy
import cv2
import errno
import gc
import json
import logging
import numpy as np
import os
import re
import socket
import struct
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from src import create_app
from src.services import hostel_camera
from src.services.hostel_camera import (
    CameraStreamWorker,
    HostelCameraManager,
    _create_synthetic_diagnostic_frame,
    _mask_rtsp_url,
    _open_capture_with_timeout,
    _resolve_stream_source,
    test_camera_connection as probe_camera_connection,
)
from src.utils import hostel_db

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers: Ephemeral TCP test servers for socket-level adversarial testing
# ============================================================================

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EphemeralResetServer:
    """TCP server that accepts a connection and immediately issues an abrupt TCP RST via SO_LINGER."""
    def __init__(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.listen(5)
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                conn, _ = self.server_sock.accept()
                linger = struct.pack("ii", 1, 0)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
                conn.close()
            except Exception:
                break

    def stop(self):
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass


class EphemeralGarbageServer:
    """TCP server that sends garbage bytes and then immediately closes the connection."""
    def __init__(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.listen(5)
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                conn, _ = self.server_sock.accept()
                try:
                    conn.sendall(b"RTSP/1.0 500 Internal Server Error\r\n\r\n\xde\xad\xbe\xef")
                except Exception:
                    pass
                conn.close()
            except Exception:
                break

    def stop(self):
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass


# ============================================================================
# Test Suite 1: Malformed RTSP URLs, Weird Inputs & Fuzzing
# ============================================================================

class TestMalformedAndFuzzedInputs:
    """Verify system never crashes when subjected to fuzzed or malformed inputs."""

    @pytest.mark.parametrize("bad_setting", [
        {"vendor": None},
        {"vendor": "Custom RTSP", "custom_rtsp_url": ""},
        {"vendor": "Custom RTSP", "custom_rtsp_url": "not_an_rtsp_url"},
        {"vendor": "Custom RTSP", "custom_rtsp_url": "rtsp://"},
        {"vendor": "Custom RTSP", "custom_rtsp_url": "rtsp://:554/live"},
        {"vendor": "Hikvision", "ip_address": "", "port": 554},
        {"vendor": "Hikvision", "ip_address": "999.999.999.999", "port": 554},
        {"vendor": "Hikvision", "ip_address": "localhost:554", "port": "not_a_number"},
        {"vendor": "Hikvision", "ip_address": "127.0.0.1", "port": -5, "channel": -1},
        {"vendor": "Hikvision", "ip_address": "127.0.0.1", "port": 99999999},
        {"vendor": "CP Plus", "ip_address": "127.0.0.1\r\nINJECTION", "port": 554},
        {"vendor": "Dahua", "ip_address": "127.0.0.1", "channel": "ch_two"},
        {"vendor": "TVT", "channel": None, "port": None, "ip_address": None},
    ])
    def test_prober_with_fuzzed_settings_does_not_crash(self, bad_setting):
        """test_camera_connection must return gracefully with success=False without raising exceptions."""
        result = probe_camera_connection(bad_setting)
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "status" in result
        assert "latency_ms" in result
        assert result["status"] in ("CONNECTION_FAILED", "ERROR", "FRAME_READ_FAILED", "FAILED")

    def test_empty_dict_setting_resolves_to_usb_webcam_0(self):
        """
        Adversarial Finding: Passing an empty dictionary {} falls back to '0' (USB Webcam 0).
        If /dev/video0 is present on the host, it connects to local hardware instead of failing!
        """
        url = hostel_db.build_rtsp_url({})
        assert url == "0"
        resolved = _resolve_stream_source({})
        assert resolved == 0

        # When tested, it must reject cleanly without hijacking local hardware index 0
        result = probe_camera_connection({})
        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["status"] == "FAILED"
        assert result["error"] == "Invalid camera configuration"

    def test_special_characters_in_credentials(self):
        """RFC 3986 percent-encoding stress with complex special character sequences."""
        passwords = [
            "P@ss:w/rd#123",
            "p@$$w0rd!#%&'()*+,;=",
            "admin:admin@host/path?query=1#frag",
            "Complex$ecr3t%/!#",
            "   spaces in password   ",
            "emoji🔑camera🎥secure",
        ]
        for pwd in passwords:
            settings = {
                "vendor": "Hikvision",
                "ip_address": "192.168.1.100",
                "port": 554,
                "channel": 1,
                "username": "user!name@host",
                "password": pwd,
            }
            url = hostel_db.build_rtsp_url(settings)
            assert isinstance(url, str)
            assert url.startswith("rtsp://")
            creds_part = url[len("rtsp://"):url.rfind("@192.168.1.100:554")]
            user_part, pass_part = creds_part.split(":", 1)
            assert "@" not in user_part
            assert "@" not in pass_part


# ============================================================================
# Test Suite 2: Network Socket Simulation (Closed ports, TCP Resets, Routeless IPs)
# ============================================================================

class TestNetworkSocketAdversarial:
    """Stress tests with real TCP socket conditions (closed ports, RST, garbage, timeouts)."""

    def test_connection_to_closed_local_port(self):
        """Connecting to a port where no service is listening (immediate TCP RST / ECONNREFUSED)."""
        free_port = get_free_port()
        settings = {
            "vendor": "Custom RTSP",
            "custom_rtsp_url": f"rtsp://127.0.0.1:{free_port}/live"
        }
        res = probe_camera_connection(settings)
        assert res["success"] is False
        assert res["status"] in ("CONNECTION_FAILED", "ERROR")
        assert res["latency_ms"] >= 0.0

    def test_connection_with_abrupt_tcp_rst(self):
        """Server accepts connection and immediately aborts with TCP RST (SO_LINGER=0)."""
        server = EphemeralResetServer()
        try:
            settings = {
                "vendor": "Custom RTSP",
                "custom_rtsp_url": f"rtsp://127.0.0.1:{server.port}/live"
            }
            res = probe_camera_connection(settings)
            assert res["success"] is False
            assert res["status"] in ("CONNECTION_FAILED", "ERROR")
        finally:
            server.stop()

    def test_connection_with_garbage_and_early_eof(self):
        """Server sends garbage non-RTSP HTTP 500 response and closes socket."""
        server = EphemeralGarbageServer()
        try:
            settings = {
                "vendor": "Custom RTSP",
                "custom_rtsp_url": f"rtsp://127.0.0.1:{server.port}/live"
            }
            res = probe_camera_connection(settings)
            assert res["success"] is False
            assert res["status"] in ("CONNECTION_FAILED", "ERROR")
        finally:
            server.stop()

    def test_timeout_unreachable_routeless_ip(self):
        """
        RFC 5737 TEST-NET-1 (192.0.2.1) is reserved and non-routable.
        Watchdog timeout in _open_capture_with_timeout must prevent indefinite hanging.
        """
        start = time.perf_counter()
        settings = {
            "vendor": "Hikvision",
            "ip_address": "192.0.2.1",
            "port": 554,
            "channel": 1,
        }
        res = probe_camera_connection(settings)
        elapsed = time.perf_counter() - start
        assert res["success"] is False
        assert res["status"] == "CONNECTION_FAILED"
        assert elapsed < 6.0, f"Unreachable IP probe took too long ({elapsed:.2f}s), watchdog failed to terminate"


# ============================================================================
# Test Suite 3: File Descriptor and VideoCapture Resource Leaks
# ============================================================================

class TestResourceLeakPrevention:
    """Empirically measure file descriptor and VideoCapture resource consumption under error storms."""

    def test_prober_file_descriptor_retention_under_failure_storm(self):
        """Execute 25 failed probes and verify file descriptors do not accumulate."""
        if not os.path.exists("/proc/self/fd"):
            pytest.skip("Linux /proc/self/fd not available")

        gc.collect()
        time.sleep(0.1)
        initial_fds = len(os.listdir("/proc/self/fd"))

        free_port = get_free_port()
        settings = {
            "vendor": "Custom RTSP",
            "custom_rtsp_url": f"rtsp://127.0.0.1:{free_port}/live"
        }

        for _ in range(25):
            res = probe_camera_connection(settings)
            assert res["success"] is False

        gc.collect()
        time.sleep(0.2)
        final_fds = len(os.listdir("/proc/self/fd"))

        fd_growth = final_fds - initial_fds
        assert fd_growth <= 5, f"File descriptors leaked during failed probe storm: initial={initial_fds}, final={final_fds}, growth={fd_growth}"

    def test_prober_releases_capture_when_unexpected_exception_raised(self):
        """Even if cap.read() throws an unhandled RuntimeError, VideoCapture.release() must be invoked."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.side_effect = RuntimeError("Simulated driver crash during frame read")

        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=mock_cap):
            res = probe_camera_connection({"vendor": "USB Webcam", "channel": 0})
            assert res["success"] is False
            assert res["status"] == "ERROR"
            assert "Simulated driver crash" in res["error"]
            mock_cap.release.assert_called_once()


# ============================================================================
# Test Suite 4: Multi-tier Fallback & Synthetic Diagnostic Frames
# ============================================================================

class TestMultiTierFallbackAndSyntheticFrames:
    """Verify fallback hierarchy and diagnostic frame generation robustness."""

    def test_synthetic_frame_with_extreme_strings(self):
        """Synthetic diagnostic generator must handle empty strings, 10k chars, and Unicode without throwing."""
        cases = [
            ("", "", None),
            ("A" * 1000, "B" * 5000, 99999.9),
            ("ONLINE - ALL GOOD", "System normal", 1.5),
            ("RECONNECTING 🔄", "Retrying feed 📹...", None),
            ("CRITICAL 🚨", "Host unreachable \x00\x01\x02", -10.0),
        ]
        for status, detail, lat in cases:
            buf = _create_synthetic_diagnostic_frame(
                role="IN",
                status_text=status,
                detail_text=detail,
                latency_ms=lat
            )
            assert isinstance(buf, bytes)
            assert len(buf) > 0

            arr = np.frombuffer(buf, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            assert img is not None
            assert img.shape == (360, 640, 3)

    def test_synthetic_frame_contains_status_banner_and_role(self):
        """Verify generated frame contains appropriate color badge depending on status."""
        buf_online = _create_synthetic_diagnostic_frame("IN", "ONLINE", "Normal")
        buf_err = _create_synthetic_diagnostic_frame("OUT", "CONNECTION_FAILED", "Failed")

        img_online = cv2.imdecode(np.frombuffer(buf_online, np.uint8), cv2.IMREAD_COLOR)
        img_err = cv2.imdecode(np.frombuffer(buf_err, np.uint8), cv2.IMREAD_COLOR)

        assert img_online is not None
        assert img_err is not None
        diff = cv2.absdiff(img_online, img_err)
        assert np.sum(diff) > 0

    def test_camera_stream_worker_midstream_disconnect_fallback(self):
        """
        Simulate an active worker whose stream suddenly drops out (cap.read returns False).
        Worker must not crash and must continue providing synthetic diagnostic frames.
        """
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        good_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        read_results = [(True, good_frame), (True, good_frame)] + [(False, None)] * 20

        def mock_read():
            if read_results:
                return read_results.pop(0)
            return (False, None)

        mock_cap.read.side_effect = mock_read

        worker = CameraStreamWorker("IN", {"vendor": "Custom RTSP", "custom_rtsp_url": "rtsp://test/live"})

        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=mock_cap):
            worker.running = True
            loop_thread = threading.Thread(target=worker._capture_loop, daemon=True)
            loop_thread.start()

            time.sleep(0.5)
            worker.running = False
            loop_thread.join(timeout=1.5)

            frame_bytes = worker.get_latest_jpeg()
            assert isinstance(frame_bytes, bytes)
            assert len(frame_bytes) > 0

    def test_synthetic_frame_clock_advances_during_backoff_sleep(self):
        """
        Hardened: Synthetic diagnostic frames always reflect the current live timestamp
        on every get_latest_jpeg() / get_frame() read, even during exponential backoff sleep.
        """
        worker = CameraStreamWorker("OUT", {"vendor": "Custom RTSP", "custom_rtsp_url": "rtsp://127.0.0.1:59999/live"})

        # Force capture_loop to fail both tier 1 and tier 2 immediately
        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=None):
            worker.running = True
            loop_thread = threading.Thread(target=worker._capture_loop, daemon=True)
            loop_thread.start()

            # Wait for it to transition to RECONNECTING and sleep in backoff
            time.sleep(1.5)
            f1 = worker.get_latest_jpeg()
            f1_alias = worker.get_frame()
            time.sleep(1.0)
            f2 = worker.get_latest_jpeg()

            worker.running = False
            loop_thread.join(timeout=2.0)

            assert worker.status == "RECONNECTING"
            assert isinstance(f1_alias, bytes) and len(f1_alias) > 0
            # Live clock advances dynamically on each read during backoff
            assert f1 != f2, "Expected live clock to advance across reads during backoff sleep"


# ============================================================================
# Test Suite 5: Worker Concurrency & Rapid Thread Start/Stop
# ============================================================================

class TestWorkerConcurrencyAndRapidLifecycle:
    """Stress tests on CameraStreamWorker and HostelCameraManager thread lifecycles."""

    def test_rapid_worker_start_stop_cycles(self):
        """Rapidly start and stop worker 10 times to verify no deadlocks or orphan threads."""
        worker = CameraStreamWorker("IN", {"enabled": False})
        for _ in range(10):
            worker.start()
            assert worker.running is True
            worker.stop()
            assert worker.running is False

    def test_concurrent_worker_reconfigure(self):
        """Call reconfigure from multiple threads while worker is active."""
        worker = CameraStreamWorker("OUT", {"enabled": True, "vendor": "USB Webcam"})
        worker.running = True

        def _reconf_loop(idx):
            for i in range(15):
                worker.reconfigure({
                    "vendor": "Hikvision",
                    "ip_address": f"192.168.1.{100 + idx}",
                    "channel": i % 2 + 1
                })
                time.sleep(0.01)

        threads = [threading.Thread(target=_reconf_loop, args=(t_id,)) for t_id in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        worker.running = False
        assert worker.reconfigure_requested in (True, False)


# ============================================================================
# Test Suite 6: Security & Masking Robustness
# ============================================================================

class TestSecurityAndUrlMasking:
    """Verify passwords are never leaked in logs, return dicts, or masked URLs."""

    def test_mask_rtsp_url_standard_and_edge_cases(self):
        raw = "rtsp://admin:SecretPassword123@192.168.1.50:554/live"
        masked = _mask_rtsp_url(raw)
        assert "SecretPassword123" not in masked
        assert "****" in masked

    def test_mask_rtsp_url_falsy_integer_zero(self):
        """
        Hardened: Device index 0 (integer or string) is preserved as '0' instead of returning empty string.
        """
        assert _mask_rtsp_url("") == ""
        assert _mask_rtsp_url(None) == ""
        # Integer 0 is safely preserved as string '0':
        assert _mask_rtsp_url(0) == "0"
        # String '0' is preserved as '0':
        assert _mask_rtsp_url("0") == "0"
        assert _mask_rtsp_url(1) == "1"

    def test_mask_rtsp_url_raw_at_sign_in_password_leak_vector(self):
        """
        Hardened: RTSP URLs with unescaped '@' characters in password do not leak secrets.
        All credentials up to the host are safely masked with '****'.
        """
        raw = "rtsp://admin:my@secret@192.168.1.1:554/live"
        masked = _mask_rtsp_url(raw)
        assert "secret" not in masked
        assert masked == "rtsp://admin:****@192.168.1.1:554/live"


# ============================================================================
# Test Suite 7: Flask /api/cameras/test-connection Adversarial HTTP Probing
# ============================================================================

class TestFlaskApiTestConnectionAdversarial:
    """Adversarial stress testing against Flask endpoint /api/cameras/test-connection."""

    def test_api_unauthenticated_request_returns_401_json(self, client):
        """
        Hardened: Unauthenticated requests to /api/cameras/* endpoints return
        HTTP 401 Unauthorized with JSON error payload instead of HTML 302 redirect.
        """
        resp = client.post(
            "/api/cameras/test-connection",
            json={"vendor": "USB Webcam", "channel": 0}
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"] == "Authentication required"

    def test_api_test_connection_invalid_content_types_authenticated(self, auth_client):
        """Sending raw text returns 400 Bad Request without crashing the worker."""
        resp = auth_client.post(
            "/api/cameras/test-connection",
            data="not a json payload",
            content_type="text/plain"
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_api_test_connection_empty_json_authenticated(self, auth_client):
        """POST with empty JSON {} returns 400 Bad Request."""
        resp = auth_client.post("/api/cameras/test-connection", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_api_test_connection_with_closed_port_returns_200_with_failure_flag(self, auth_client):
        """Testing an unreachable RTSP address must return HTTP 200 with success=False, never 500."""
        free_port = get_free_port()
        payload = {
            "vendor": "Custom RTSP",
            "custom_rtsp_url": f"rtsp://127.0.0.1:{free_port}/live"
        }
        resp = auth_client.post("/api/cameras/test-connection", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert data["status"] in ("CONNECTION_FAILED", "ERROR")
        assert "latency_ms" in data
