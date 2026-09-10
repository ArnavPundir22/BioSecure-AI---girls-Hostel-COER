"""
End-to-End (E2E) Test Suite for CCTV Camera Setup Management System.
Covers:
1. Administrative UI page rendering (/admin/cameras) with role authorization.
2. JSON API endpoints (/api/cameras/settings, /api/cameras/test-connection, /api/cameras/save).
3. Hot-reloading and cross-process notification integration.
4. Hostel Warden Dashboard navigation links and dual-gate MJPEG feeds (/video_feed?role=IN/OUT).
5. Complete decoupling verification of WebRTC student face registration (Requirement R5).
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch
import numpy as np


class TestAdminCameraSetupUI:
    """E2E testing of the administrative Camera Setup portal."""

    def test_e2e_admin_cameras_unauthenticated_access(self, client):
        """Unauthenticated requests to /admin/cameras should not grant admin access."""
        resp = client.get("/admin/cameras")
        # Renders login template or redirects
        assert resp.status_code in (200, 302)
        html = resp.get_data(as_text=True)
        if resp.status_code == 200:
            assert "Admin access required" in html or "Login" in html

    def test_e2e_admin_cameras_authenticated_render(self, auth_client):
        """Authenticated admin access to /admin/cameras renders the complete CCTV setup interface."""
        resp = auth_client.get("/admin/cameras")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Verify key UI components and elements
        assert "CCTV Camera Setup" in html
        assert "IN Gate (Entry Gate)" in html
        assert "OUT Gate (Exit Gate)" in html
        assert "CAM_01_ENTRY" in html
        assert "CAM_02_EXIT" in html

        # Verify vendor presets in dropdowns
        for vendor in ("Hikvision", "CP Plus", "Dahua", "TVT", "Custom RTSP", "USB Webcam"):
            assert vendor in html

        # Verify action buttons and test prober modal
        assert "Test Connection" in html
        assert "probeModal" in html
        assert "Save All Configurations" in html


class TestCCTVCameraAPIEndpoints:
    """E2E testing of /api/cameras/* JSON API endpoints."""

    def test_e2e_get_camera_settings_api(self, auth_client):
        """GET /api/cameras/settings returns JSON with masked passwords and active stream configs."""
        resp = auth_client.get("/api/cameras/settings")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["success"] is True
        assert "cameras" in data
        assert "IN" in data["cameras"]
        assert "OUT" in data["cameras"]

        # Passwords must be masked for telemetry
        for role in ("IN", "OUT"):
            cam = data["cameras"][role]
            assert cam["camera_role"] == role
            if cam.get("password"):
                assert cam["password"] == "••••••••"
            assert "rtsp_url" in cam

    def test_e2e_test_connection_api_success(self, auth_client):
        """POST /api/cameras/test-connection with mock stream returns success, metrics, and thumbnail."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, dummy_frame)
        mock_cap.get.return_value = 25.0

        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=mock_cap):
            payload = {
                "camera_role": "IN",
                "vendor": "Hikvision",
                "ip_address": "192.168.1.100",
                "port": 554,
                "channel": 1,
                "username": "admin",
                "password": "pass",
            }
            resp = auth_client.post("/api/cameras/test-connection", json=payload)
            assert resp.status_code == 200
            data = resp.get_json()

            assert data["success"] is True
            assert data["status"] == "CONNECTED"
            assert data["resolution"] == "1280x720"
            assert data["fps"] == 25.0
            assert "preview_image" in data
            assert data["preview_image"].startswith("data:image/jpeg;base64,")

    def test_e2e_test_connection_api_failure(self, auth_client):
        """POST /api/cameras/test-connection handles offline camera gracefully."""
        with patch("src.services.hostel_camera._open_capture_with_timeout", return_value=None):
            payload = {
                "camera_role": "IN",
                "vendor": "Hikvision",
                "ip_address": "192.168.1.250",
                "port": 554,
            }
            resp = auth_client.post("/api/cameras/test-connection", json=payload)
            assert resp.status_code == 200
            data = resp.get_json()

            assert data["success"] is False
            assert data["status"] == "CONNECTION_FAILED"
            assert "Could not connect" in data["error"]

    def test_e2e_save_camera_settings_api(self, auth_client, mock_db):
        """POST /api/cameras/save persists configuration and reloads streaming workers."""
        payload = {
            "IN": {
                "vendor": "CP Plus",
                "ip_address": "10.0.0.88",
                "port": 554,
                "channel": 1,
                "username": "admin",
                "password": "NewSecretPassword",
                "resolution": "1920x1080",
                "fps": 30,
                "enabled": True,
            },
            "OUT": {
                "vendor": "Dahua",
                "ip_address": "10.0.0.89",
                "port": 554,
                "channel": 2,
                "username": "admin",
                "password": "NewSecretPassword2",
                "resolution": "1920x1080",
                "fps": 30,
                "enabled": True,
            }
        }

        with patch("src.services.hostel_camera.get_camera_manager") as mock_mgr_factory:
            mock_mgr = MagicMock()
            mock_mgr_factory.return_value = mock_mgr

            resp = auth_client.post("/api/cameras/save", json=payload)
            assert resp.status_code == 200
            data = resp.get_json()

            assert data["success"] is True
            assert "saved_roles" in data
            assert "IN" in data["saved_roles"]
            assert "OUT" in data["saved_roles"]

            # Verify reload was invoked on camera manager
            mock_mgr.reload_camera_configurations.assert_called_once()

        # Verify DB store was updated
        in_db = [r for r in mock_db.tables["camera_settings"] if r.get("camera_role") == "IN"][0]
        assert in_db["vendor"] == "CP Plus"
        assert in_db["ip_address"] == "10.0.0.88"


class TestHostelDashboardIntegration:
    """E2E testing of Hostel Dashboard navigation and dual gate stream endpoints."""

    def test_e2e_hostel_dashboard_navigation_links(self, auth_client):
        """Hostel dashboard includes Camera Setup link and CAM 01/CAM 02 feed configurations."""
        resp = auth_client.get("/hostel/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Header nav link
        assert '/admin/cameras' in html
        assert 'Camera Setup' in html

        # Feeds mapped to roles
        assert '/hostel/video_feed?role=IN' in html
        assert '/hostel/video_feed?role=OUT' in html

    def test_e2e_video_feed_streaming_endpoints(self, auth_client):
        """MJPEG video feed endpoints support role query parameters and dedicated aliases."""
        resp_in = auth_client.get("/hostel/video_feed?role=IN")
        assert resp_in.status_code == 200
        assert "multipart/x-mixed-replace" in resp_in.headers.get("Content-Type", "")

        resp_out = auth_client.get("/hostel/video_feed?role=OUT")
        assert resp_out.status_code == 200
        assert "multipart/x-mixed-replace" in resp_out.headers.get("Content-Type", "")

        # Dedicated aliases
        resp_alias_in = auth_client.get("/hostel/video_feed/in")
        assert resp_alias_in.status_code == 200

        resp_alias_out = auth_client.get("/hostel/video_feed/out")
        assert resp_alias_out.status_code == 200

    def test_e2e_video_frame_single_jpeg(self, auth_client):
        """Single frame snapshot endpoint returns valid JPEG image."""
        resp = auth_client.get("/hostel/video_frame?role=IN")
        assert resp.status_code == 200
        assert resp.headers.get("Content-Type") == "image/jpeg"
        assert len(resp.data) > 0


class TestWebRTCStudentRegistrationDecoupling:
    """Verification of Requirement R5: Student face registration remains 100% client WebRTC."""

    def test_e2e_student_registration_page_webrtc(self, auth_client):
        """Student registration page (/add_student) utilizes client-side GuidedCameraEngine."""
        resp = auth_client.get("/add_student")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert "guided-camera.js" in html
        assert "face-api.js" in html
        # Zero reliance on server DVR video feeds
        assert "/hostel/video_feed" not in html

    def test_e2e_guided_camera_js_uses_getusermedia(self):
        """Verify guided-camera.js explicitly calls navigator.mediaDevices.getUserMedia."""
        js_path = os.path.join(os.path.dirname(__file__), "../../src/static/js/guided-camera.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        assert "navigator.mediaDevices.getUserMedia" in js_content
        assert "srcObject" in js_content
        # Confirm student registration has zero references to backend DVR hardware lock
        assert "hostel_camera_device.lock" not in js_content
