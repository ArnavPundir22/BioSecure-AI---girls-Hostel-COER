"""
Unit Tests for JWT Authentication & Route Protection — BioSecure AI Girls Hostel.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import jwt
from src import create_app, config
from src.utils.auth_helpers import generate_jwt_token, decode_jwt_token


class TestJWTAuthentication(unittest.TestCase):
    """Test suite for JWT token generation, decoding, and route protection."""

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def test_generate_and_decode_jwt_token(self):
        """Verify JWT token contains correct claims and decodes cleanly."""
        user_id = "user-12345"
        email = "warden@coer.ac.in"
        username = "warden_jane"
        is_admin = True

        token = generate_jwt_token(user_id=user_id, email=email, username=username, is_admin=is_admin)
        self.assertIsInstance(token, str)

        payload = decode_jwt_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("user_id"), user_id)
        self.assertEqual(payload.get("email"), email)
        self.assertEqual(payload.get("username"), username)
        self.assertTrue(payload.get("is_admin"))

    def test_expired_jwt_token(self):
        """Verify expired JWT token returns None when decoded."""
        now = datetime.now(timezone.utc) - timedelta(hours=25)
        expired_payload = {
            "user_id": "user-expired",
            "email": "old@coer.ac.in",
            "username": "expired_user",
            "is_admin": False,
            "iat": now - timedelta(hours=1),
            "exp": now
        }
        expired_token = jwt.encode(expired_payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)
        
        decoded = decode_jwt_token(expired_token)
        self.assertIsNone(decoded)

    def test_unauthenticated_access_redirects_to_login(self):
        """Verify accessing /hostel/ without a JWT token redirects to /login."""
        response = self.client.get("/hostel/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_unauthenticated_api_returns_401(self):
        """Verify calling /hostel/api/stats without JWT returns 401 Unauthorized."""
        response = self.client.get("/hostel/api/stats", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertEqual(data.get("error"), "Authentication required")

    def test_authenticated_access_with_jwt_cookie(self):
        """Verify accessing protected hostel route with valid JWT cookie succeeds."""
        token = generate_jwt_token("user-777", "warden@hostel.in", "warden_user", is_admin=True)
        self.client.set_cookie("jwt_access_token", token)

        with patch("src.utils.hostel_db.fetch_all_hostel_students", return_value=[]), \
             patch("src.utils.hostel_db.fetch_overdue_curfew_students", return_value=[]):
            response = self.client.get("/hostel/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"GIRLS HOSTEL", response.data)

    def test_login_flow_redirects_to_hostel(self):
        """Verify successful login issues JWT token and redirects strictly to hostel dashboard."""
        mock_user = MagicMock()
        mock_user.id = "supa-user-999"
        mock_user.email = "warden@coer.ac.in"
        mock_user.user_metadata = {"username": "warden_test", "is_admin": True}

        mock_auth_resp = MagicMock()
        mock_auth_resp.user = mock_user

        with patch("src.blueprints.auth.supabase.auth.sign_in_with_password", return_value=mock_auth_resp):
            response = self.client.post("/login", data={
                "email": "warden@coer.ac.in",
                "password": "password123"
            })

            # Check redirect to /hostel/
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith("/hostel/") or "/hostel" in response.location)
            
            # Check JWT cookie is present
            cookie = response.headers.get("Set-Cookie")
            self.assertIn("jwt_access_token=", cookie)


if __name__ == "__main__":
    unittest.main()
