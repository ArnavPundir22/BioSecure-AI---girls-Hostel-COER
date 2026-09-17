"""
Unit Tests for Delete Student Feature — BioSecure AI Girls Hostel.
"""

import pytest
import uuid
import numpy as np
from src.utils import hostel_db
from src.utils.face_cache import add_student_to_cache, remove_student_from_cache, reload_face_cache
from src.utils.auth_helpers import generate_jwt_token


@pytest.fixture(autouse=True)
def reset_db_client():
    """Ensure clean isolated in-memory hostel DB mock for each test."""
    hostel_db.reset_hostel_client()
    client = hostel_db.get_mock_client()
    yield client
    hostel_db.reset_hostel_client()


def _create_test_student(client, name="Priya Sharma", roll="2200101", room="A-101", current_status="IN"):
    payload = {
        "name": name,
        "roll_number": roll,
        "room_number": room,
        "hostel_block": "Block-A",
        "parent_contact": "+91 9876543210",
        "student_contact": "+91 9123456789",
        "current_status": current_status
    }
    res = client.table("student_profiles").insert(payload).execute()
    return res.data[0]


def _get_authenticated_client(auth_client):
    token = generate_jwt_token("00000000-0000-0000-0000-000000000001", "warden@hostel.in", "warden", is_admin=True)
    auth_client.set_cookie("jwt_access_token", token)
    return auth_client


class TestDeleteStudentDbUnit:
    """Direct database utility tests for delete_student_profile."""

    def test_delete_student_profile_success(self, reset_db_client):
        student = _create_test_student(reset_db_client, name="Kavya Verma", roll="2200505", room="B-201")
        student_id = student["id"]

        success, msg, deleted = hostel_db.delete_student_profile(
            student_id=student_id,
            client=reset_db_client
        )

        assert success is True
        assert "deleted successfully" in msg
        assert deleted is not None
        assert deleted["name"] == "Kavya Verma"

        # Verify student is removed from database
        remaining = hostel_db.fetch_all_hostel_students(client=reset_db_client)
        assert not any(s["id"] == student_id for s in remaining)

    def test_delete_student_profile_not_found(self, reset_db_client):
        fake_id = str(uuid.uuid4())
        success, msg, deleted = hostel_db.delete_student_profile(
            student_id=fake_id,
            client=reset_db_client
        )

        assert success is False
        assert "not found" in msg
        assert deleted is None


class TestDeleteStudentApi:
    """Flask REST API integration tests for /hostel/api/delete_student/<student_id>."""

    def test_delete_student_api_success(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c, name="Simran Kaur", roll="2200606", room="C-302")
        student_id = student["id"]

        resp = c.delete(f"/hostel/api/delete_student/{student_id}")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "deleted successfully" in data["message"]
        assert data["student"]["name"] == "Simran Kaur"

    def test_delete_student_api_post_method_success(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c, name="Neha Roy", roll="2200707", room="D-102")
        student_id = student["id"]

        resp = c.post(f"/hostel/api/delete_student/{student_id}")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["student"]["name"] == "Neha Roy"

    def test_delete_student_api_not_found(self, auth_client):
        c = _get_authenticated_client(auth_client)
        fake_id = str(uuid.uuid4())

        resp = c.delete(f"/hostel/api/delete_student/{fake_id}")

        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"]
