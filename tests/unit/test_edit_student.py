"""
Unit Tests for Edit Student Details Feature — BioSecure AI Girls Hostel.
"""

import pytest
import uuid
import numpy as np
from src.utils import hostel_db
from src.utils.face_cache import add_student_to_cache, reload_face_cache


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


from src.utils.auth_helpers import generate_jwt_token


def _get_authenticated_client(auth_client):
    token = generate_jwt_token("00000000-0000-0000-0000-000000000001", "warden@hostel.in", "warden", is_admin=True)
    auth_client.set_cookie("jwt_access_token", token)
    return auth_client




class TestEditStudentDbUnit:
    """Direct database utility tests for update_student_profile."""

    def test_update_student_profile_success(self, reset_db_client):
        student = _create_test_student(reset_db_client, name="Priya Sharma", roll="2200101", room="A-101")
        student_id = student["id"]

        updates = {
            "name": "Priya V. Sharma",
            "roll_number": "2200101",
            "room_number": "A-205",
            "hostel_block": "Block-B",
            "parent_contact": "+91 9998887770",
            "student_contact": "+91 9112223334"
        }

        success, msg, updated = hostel_db.update_student_profile(
            student_id=student_id,
            updates=updates,
            client=reset_db_client
        )

        assert success is True
        assert "updated successfully" in msg
        assert updated is not None
        assert updated["name"] == "Priya V. Sharma"
        assert updated["room_number"] == "A-205"
        assert updated["hostel_block"] == "Block-B"
        assert updated["parent_contact"] == "+91 9998887770"

    def test_update_student_profile_duplicate_roll_number(self, reset_db_client):
        s1 = _create_test_student(reset_db_client, name="Student One", roll="ROLL001", room="A-101")
        s2 = _create_test_student(reset_db_client, name="Student Two", roll="ROLL002", room="A-102")

        # Try updating s2's roll number to s1's roll number (ROLL001)
        updates = {
            "name": "Student Two Updated",
            "roll_number": "ROLL001",
            "room_number": "A-102",
            "parent_contact": "+91 9876543210"
        }

        success, msg, updated = hostel_db.update_student_profile(
            student_id=s2["id"],
            updates=updates,
            client=reset_db_client
        )

        assert success is False
        assert "already assigned to another student" in msg
        assert updated is None

    def test_update_student_profile_not_found(self, reset_db_client):
        fake_id = str(uuid.uuid4())
        updates = {
            "name": "Ghost Student",
            "roll_number": "ROLL999",
            "room_number": "B-101",
            "parent_contact": "+91 9876543210"
        }

        success, msg, updated = hostel_db.update_student_profile(
            student_id=fake_id,
            updates=updates,
            client=reset_db_client
        )

        assert success is False
        assert "not found" in msg
        assert updated is None


class TestEditStudentApi:
    """Flask REST API integration tests for /hostel/api/update_student/<student_id>."""

    def test_update_student_api_json_success(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c, name="Ananya Gupta", roll="2200202", room="A-301")
        student_id = student["id"]

        resp = c.post(
            f"/hostel/api/update_student/{student_id}",
            json={
                "name": "Ananya K. Gupta",
                "roll_number": "2200202-UPDATED",
                "room_number": "B-402",
                "hostel_block": "Block-B",
                "parent_contact": "+91 9876500000",
                "student_contact": "+91 9123400000"
            }
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "updated successfully" in data["message"]
        assert data["student"]["name"] == "Ananya K. Gupta"
        assert data["student"]["roll_number"] == "2200202-UPDATED"
        assert data["student"]["room_number"] == "B-402"

    def test_update_student_api_form_success(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c, name="Riya Patel", roll="2200303", room="C-101")
        student_id = student["id"]

        resp = c.post(
            f"/hostel/api/update_student/{student_id}",
            data={
                "name": "Riya M. Patel",
                "roll_number": "2200303",
                "room_number": "C-102",
                "hostel_block": "Block-C",
                "parent_contact": "+91 9991112223",
                "student_contact": "+91 9882223334"
            }
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["student"]["name"] == "Riya M. Patel"
        assert data["student"]["room_number"] == "C-102"

    def test_update_student_api_missing_fields(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c)

        # Missing parent_contact
        resp = c.post(
            f"/hostel/api/update_student/{student['id']}",
            json={
                "name": "Test Name",
                "roll_number": "99999",
                "room_number": "A-101"
            }
        )

        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"]

    def test_update_student_api_duplicate_roll(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        s1 = _create_test_student(mock_c, roll="EXISTING_ROLL_1")
        s2 = _create_test_student(mock_c, roll="EXISTING_ROLL_2")

        resp = c.post(
            f"/hostel/api/update_student/{s2['id']}",
            json={
                "name": s2["name"],
                "roll_number": "EXISTING_ROLL_1",
                "room_number": s2["room_number"],
                "parent_contact": s2["parent_contact"]
            }
        )

        assert resp.status_code == 400
        assert "already assigned to another student" in resp.get_json()["error"]
