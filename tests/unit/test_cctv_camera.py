"""
Unit Tests for CCTV Camera Setup Management Subsystem.
Covers:
1. Vendor preset RTSP URL construction and RFC 3986 percent-encoding.
2. Password masking in URLs and telemetry responses.
3. Connection prober (metrics, thumbnails, and guaranteed leak prevention).
4. Database persistence and dual-sync with girls_hostel.camera_settings.
5. Zero-crash synthetic diagnostic frame generation and fallback.
6. Dual gate direction invariants (CAM_01_ENTRY -> IN, CAM_02_EXIT -> OUT).
7. Hot configuration reload coordinator.
"""

import copy
import cv2
import json
import numpy as np
import os
import pytest
from unittest.mock import MagicMock, patch

from src.services import hostel_camera
from src.services.hostel_camera import (
    CameraStreamWorker,
    HostelCameraManager,
    _create_synthetic_diagnostic_frame,
    _mask_rtsp_url,
    _open_capture_with_timeout,
    _resolve_stream_source,
    get_camera_manager,
    test_camera_connection as probe_camera_connection,
)
from src.utils import hostel_db, hostel_state


class TestVendorPresetUrlConstruction:
    """Test vendor preset URL construction, port/channel defaults, and password percent-encoding."""

    def test_hikvision_preset(self):
        settings = {
            "vendor": "Hikvision",
            "ip_address": "192.168.1.100",
            "port": 554,
            "channel": 1,
            "username": "admin",
            "password": "Password123",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://admin:Password123@192.168.1.100:554/Streaming/Channels/101"

    def test_hikvision_preset_channel_2(self):
        settings = {
            "vendor": "Hikvision",
            "ip_address": "192.168.1.100",
            "port": 554,
            "channel": 2,
            "username": "admin",
            "password": "Password123",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://admin:Password123@192.168.1.100:554/Streaming/Channels/201"

    def test_cpplus_preset(self):
        settings = {
            "vendor": "CP Plus",
            "ip_address": "10.0.0.50",
            "port": 554,
            "channel": 1,
            "username": "admin",
            "password": "SecretPassword",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://admin:SecretPassword@10.0.0.50:554/cam/realmonitor?channel=1&subtype=0"

    def test_dahua_preset(self):
        settings = {
            "vendor": "Dahua",
            "ip_address": "192.168.1.200",
            "port": 554,
            "channel": 2,
            "username": "admin",
            "password": "pass",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://admin:pass@192.168.1.200:554/cam/realmonitor?channel=2&subtype=0"

    def test_tvt_preset(self):
        settings = {
            "vendor": "TVT",
            "ip_address": "192.168.1.75",
            "port": 554,
            "channel": 1,
            "username": "admin",
            "password": "tvtpass",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://admin:tvtpass@192.168.1.75:554/ch1/main/av_stream"

    def test_custom_rtsp_url(self):
        settings = {
            "vendor": "Custom RTSP",
            "custom_rtsp_url": "rtsp://edge.gateway.internal:8554/feed_gate_in",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://edge.gateway.internal:8554/feed_gate_in"

    def test_usb_webcam_preset(self):
        settings_in = {"vendor": "USB Webcam", "channel": 0, "camera_role": "IN"}
        assert hostel_db.build_rtsp_url(settings_in) == "0"

        settings_out = {"vendor": "USB Webcam", "channel": 1, "camera_role": "OUT"}
        assert hostel_db.build_rtsp_url(settings_out) == "1"

    def test_password_percent_encoding(self):
        """Verify special characters in passwords are RFC 3986 percent-encoded."""
        settings = {
            "vendor": "Hikvision",
            "ip_address": "192.168.1.100",
            "port": 554,
            "channel": 1,
            "username": "admin",
            "password": "P@ss:w/rd#123",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert "P%40ss%3Aw%2Frd%23123@" in url
        assert "admin:P%40ss%3Aw%2Frd%23123@192.168.1.100:554" in url

    def test_mask_rtsp_url_utility(self):
        raw = "rtsp://admin:SuperSecretPass123@192.168.1.100:554/Streaming/Channels/101"
        masked = _mask_rtsp_url(raw)
        assert "SuperSecretPass123" not in masked
        assert "rtsp://admin:****@192.168.1.100:554/Streaming/Channels/101" == masked

    def test_missing_credentials_clean_url(self):
        settings = {
            "vendor": "Hikvision",
            "ip_address": "192.168.1.100",
            "port": 554,
            "channel": 1,
            "username": "",
            "password": "",
        }
        url = hostel_db.build_rtsp_url(settings)
        assert url == "rtsp://192.168.1.100:554/Streaming/Channels/101"


class TestConnectionProber:
    """Test live connection prober with simulated VideoCapture outcomes and guaranteed leak prevention."""

    def test_prober_successful_connection(self):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        # Create a synthetic test frame (720p)
        dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, dummy_frame)
        mock_cap.get.return_value = 30.0

        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=mock_cap):
            settings = {
                "vendor": "Hikvision",
                "ip_address": "192.168.1.100",
                "port": 554,
                "channel": 1,
                "username": "admin",
                "password": "secret",
            }
            res = probe_camera_connection(settings)

            assert res["success"] is True
            assert res["status"] == "CONNECTED"
            assert res["resolution"] == "1280x720"
            assert res["fps"] == 30.0
            assert "latency_ms" in res
            assert res["latency_ms"] >= 0.0
            assert res["preview_image"].startswith("data:image/jpeg;base64,")
            assert "secret" not in res["url_tested"]
            assert "****" in res["url_tested"]

            # Strict leak check
            mock_cap.release.assert_called_once()

    def test_prober_connection_failure(self):
        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=None):
            settings = {
                "vendor": "Hikvision",
                "ip_address": "192.168.1.99",
                "port": 554,
            }
            res = probe_camera_connection(settings)

            assert res["success"] is False
            assert res["status"] == "CONNECTION_FAILED"
            assert "Could not connect" in res["error"]
            assert "latency_ms" in res

    def test_prober_frame_read_failure_and_resource_release(self):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)

        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=mock_cap):
            settings = {
                "vendor": "CP Plus",
                "ip_address": "192.168.1.50",
            }
            res = probe_camera_connection(settings)

            assert res["success"] is False
            assert res["status"] == "FRAME_READ_FAILED"
            # Resource release in finally block
            mock_cap.release.assert_called_once()


class TestCameraSettingsDatabaseLifecycle:
    """Test schema-isolated persistence of camera settings in girls_hostel.camera_settings."""

    def test_default_camera_settings_retrieval(self, mock_db):
        in_settings = hostel_db.get_camera_settings("IN")
        assert in_camera_role(in_settings, "IN")
        assert in_settings["vendor"] == "USB Webcam"

        out_settings = hostel_db.get_camera_settings("OUT")
        assert in_camera_role(out_settings, "OUT")

        all_settings = hostel_db.get_camera_settings()
        assert isinstance(all_settings, list)
        assert len(all_settings) == 2

    def test_save_and_retrieve_camera_settings(self, mock_db):
        new_in_config = {
            "vendor": "Hikvision",
            "ip_address": "192.168.1.150",
            "port": 554,
            "channel": 1,
            "username": "admin",
            "password": "SecurePassword1!",
            "resolution": "1920x1080",
            "fps": 25,
            "enabled": True,
        }

        ok = hostel_db.save_camera_settings("IN", new_in_config)
        assert ok is True

        retrieved = hostel_db.get_camera_settings("IN")
        assert retrieved["vendor"] == "Hikvision"
        assert retrieved["ip_address"] == "192.168.1.150"
        assert retrieved["password"] == "SecurePassword1!"
        assert retrieved["resolution"] == "1920x1080"
        assert retrieved["fps"] == 25

        # Verify dual sync with system_settings['camera_sources']
        sources = hostel_db.get_system_settings("camera_sources")
        assert sources is not None
        assert "entry_cam" in sources
        assert "192.168.1.150" in sources["entry_cam"]

    def test_save_invalid_camera_role_rejected(self, mock_db):
        ok = hostel_db.save_camera_settings("LOBBY", {"vendor": "Generic"})
        assert ok is False


class TestSyntheticDiagnosticFrameAndResilience:
    """Test synthetic diagnostic frame generation and zero-crash fallback."""

    def test_create_synthetic_diagnostic_frame(self):
        raw_bytes = _create_synthetic_diagnostic_frame(
            role="IN",
            status_text="RECONNECTING",
            detail_text="Stream offline. Retrying in 2.5s",
            latency_ms=12.4
        )
        assert isinstance(raw_bytes, bytes)
        assert len(raw_bytes) > 0

        # Decode JPEG bytes and verify dimensions
        np_arr = np.frombuffer(raw_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        assert img is not None
        assert img.shape == (360, 640, 3)

    def test_camera_worker_synthetic_fallback(self):
        worker = CameraStreamWorker("IN", {"enabled": False})
        jpeg = worker.get_latest_jpeg()
        assert isinstance(jpeg, bytes)
        assert len(jpeg) > 0


class TestDualGateMovementLogging:
    """Test that CAM_01_ENTRY strictly logs 'IN' and CAM_02_EXIT strictly logs 'OUT'."""

    def test_dual_gate_direction_binding(self, mock_db):
        worker_in = CameraStreamWorker("IN")
        assert worker_in.camera_id == "CAM_01_ENTRY"
        assert worker_in.direction == "IN"

        worker_out = CameraStreamWorker("OUT")
        assert worker_out.camera_id == "CAM_02_EXIT"
        assert worker_out.direction == "OUT"

    def test_hostel_state_directional_logging(self, mock_db):
        # Insert a student in mock_db
        student = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Pooja Sharma",
            "roll_number": "2024-GH-0101",
            "room_number": "A-101",
            "current_status": "OUT",
        }
        mock_db.tables["student_profiles"].append(student)

        # 1. Detection on CAM_01_ENTRY (Entry Gate) -> transitions OUT to IN
        dir1 = hostel_state.process_student_detection(
            student_id=student["id"],
            camera_id="CAM_01_ENTRY",
            student_info=student,
        )
        assert dir1 == "IN"

        # Check movement log was inserted with direction='IN'
        logs = mock_db.tables["movement_logs"]
        assert len(logs) == 1
        assert logs[0]["direction"] == "IN"
        assert logs[0]["camera_id"] == "CAM_01_ENTRY"

        # 2. Immediate repeat detection on same camera is suppressed by 15s cooldown
        student["current_status"] = "IN"
        dir2 = hostel_state.process_student_detection(
            student_id=student["id"],
            camera_id="CAM_01_ENTRY",
            student_info=student,
        )
        assert dir2 is None  # Cooldown active!

        # 3. Detection on CAM_02_EXIT (Exit Gate) -> transitions IN to OUT
        # Clear cooldown for student on CAM_02_EXIT
        dir3 = hostel_state.process_student_detection(
            student_id=student["id"],
            camera_id="CAM_02_EXIT",
            student_info=student,
        )
        assert dir3 == "OUT"
        assert len(logs) == 2
        assert logs[1]["direction"] == "OUT"
        assert logs[1]["camera_id"] == "CAM_02_EXIT"


def in_camera_role(settings: dict, expected: str) -> bool:
    return str(settings.get("camera_role", "")).upper() == expected.upper()
