"""
Unit Tests for Manual Warden IN/OUT Entry Feature — BioSecure AI Girls Hostel.
"""

import pytest
import uuid
from src.utils import hostel_db


@pytest.fixture(autouse=True)
def reset_db_client():
    """Ensure clean isolated in-memory hostel DB mock for each test."""
    hostel_db.reset_hostel_client()
    client = hostel_db.get_mock_client()
    yield client
    hostel_db.reset_hostel_client()


def _create_test_student(client, name="Ananya test", roll="99901", room="A-101", current_status="IN"):
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


class TestManualMovementUnit:
    """Direct database utility tests for record_manual_movement."""

    def test_record_manual_movement_out_success(self, reset_db_client):
        student = _create_test_student(reset_db_client, current_status="IN")
        student_id = student["id"]

        success, msg, updated = hostel_db.record_manual_movement(
            student_id=student_id,
            direction="OUT",
            notes="Gate pass #402 - Weekend leave",
            client=reset_db_client
        )

        assert success is True
        assert "Manual OUT entry recorded" in msg
        assert updated is not None
        assert updated["current_status"] == "OUT"

        # Check movement log
        logs = hostel_db.get_recent_movement_logs(limit=10, client=reset_db_client)
        assert len(logs) == 1
        assert logs[0]["student_id"] == student_id
        assert logs[0]["direction"] == "OUT"
        assert logs[0]["camera_id"] == "MANUAL_ENTRY"
        assert logs[0]["notes"] == "Gate pass #402 - Weekend leave"

    def test_record_manual_movement_in_resolves_curfew_alert(self, reset_db_client):
        # 1. Create student currently OUT
        student = _create_test_student(reset_db_client, current_status="OUT")
        student_id = student["id"]

        # 2. Create active overdue curfew alert for student
        alert_id = hostel_db.create_curfew_alert(
            student_id=student_id,
            status="OVERDUE_OUT",
            client=reset_db_client
        )
        assert alert_id is not None

        # Verify alert is active
        active_alerts = hostel_db.get_active_curfew_alerts(client=reset_db_client)
        assert len(active_alerts) == 1

        # 3. Record manual IN entry
        success, msg, updated = hostel_db.record_manual_movement(
            student_id=student_id,
            direction="IN",
            notes="Checked in at warden desk late with permission",
            client=reset_db_client
        )

        assert success is True
        assert updated["current_status"] == "IN"
        assert "Auto-resolved 1 overdue curfew alert" in msg

        # 4. Verify curfew alert is now resolved
        active_alerts_after = hostel_db.get_active_curfew_alerts(client=reset_db_client)
        assert len(active_alerts_after) == 0

    def test_record_manual_movement_invalid_direction(self, reset_db_client):
        student = _create_test_student(reset_db_client)
        success, msg, updated = hostel_db.record_manual_movement(
            student_id=student["id"],
            direction="SIDEWAYS",
            client=reset_db_client
        )
        assert success is False
        assert "Invalid movement direction" in msg
        assert updated is None

    def test_record_manual_movement_nonexistent_student(self, reset_db_client):
        fake_id = str(uuid.uuid4())
        success, msg, updated = hostel_db.record_manual_movement(
            student_id=fake_id,
            direction="IN",
            client=reset_db_client
        )
        assert success is False
        assert "not found" in msg


from src.utils.auth_helpers import generate_jwt_token


def _get_authenticated_client(app_client):
    token = generate_jwt_token("00000000-0000-0000-0000-000000000001", "warden@hostel.in", "warden", is_admin=True)
    app_client.set_cookie("jwt_access_token", token)
    return app_client


class TestManualMovementApi:
    """Flask API integration tests for /hostel/api/manual_entry."""

    def test_manual_entry_api_json_success(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c, current_status="IN")

        resp = c.post(
            "/hostel/api/manual_entry",
            json={
                "student_id": student["id"],
                "direction": "OUT",
                "notes": "Medical emergency exit"
            }
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "Manual OUT entry recorded" in data["message"]
        assert data["student"]["current_status"] == "OUT"

    def test_manual_entry_api_form_success(self, auth_client):
        c = _get_authenticated_client(auth_client)
        mock_c = hostel_db.get_mock_client()
        student = _create_test_student(mock_c, current_status="OUT")

        resp = c.post(
            "/hostel/api/manual_entry",
            data={
                "student_id": student["id"],
                "direction": "IN",
                "notes": "Manual gate pass"
            }
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["student"]["current_status"] == "IN"

    def test_manual_entry_api_missing_fields(self, auth_client):
        c = _get_authenticated_client(auth_client)
        # Missing student_id
        resp1 = c.post("/hostel/api/manual_entry", json={"direction": "IN"})
        assert resp1.status_code == 400
        assert "student_id is required" in resp1.get_json()["error"]

        # Missing direction
        resp2 = c.post("/hostel/api/manual_entry", json={"student_id": "123"})
        assert resp2.status_code == 400
        assert "direction" in resp2.get_json()["error"]

    def test_manual_entry_api_invalid_student(self, auth_client):
        c = _get_authenticated_client(auth_client)
        fake_id = str(uuid.uuid4())
        resp = c.post(
            "/hostel/api/manual_entry",
            json={
                "student_id": fake_id,
                "direction": "IN"
            }
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"]
