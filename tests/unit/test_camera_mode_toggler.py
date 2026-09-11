"""
Unit tests for Single Webcam Camera Mode Toggler — BioSecure AI Girls Hostel.
Verifies camera_mode manager operations, state machine transitions, and API endpoints.
"""

import pytest
from src.services.hostel_camera import HostelCameraManager, get_camera_manager
from src.utils import hostel_state


def test_camera_manager_mode_get_set():
    """Test camera mode getter, setter, and invalid value validation."""
    mgr = get_camera_manager()
    
    # Test setting valid modes
    assert mgr.set_camera_mode("AUTO") == "AUTO"
    assert mgr.get_camera_mode() == "AUTO"
    
    assert mgr.set_camera_mode("IN") == "IN"
    assert mgr.get_camera_mode() == "IN"
    
    assert mgr.set_camera_mode("OUT") == "OUT"
    assert mgr.get_camera_mode() == "OUT"

    assert mgr.set_camera_mode("DUAL") == "DUAL"
    assert mgr.get_camera_mode() == "DUAL"

    # Test setting invalid mode raises ValueError
    with pytest.raises(ValueError):
        mgr.set_camera_mode("INVALID_MODE")


def test_hostel_state_camera_mode_directions(monkeypatch):
    """Test hostel_state.process_student_detection under AUTO, IN, and OUT modes."""
    # Mock update_student_movement_state to avoid DB dependency in unit tests
    updated_records = []
    def dummy_update(student_id, direction, camera_id):
        updated_records.append((student_id, direction, camera_id))
        return True
    
    monkeypatch.setattr("src.utils.hostel_db.update_student_movement_state", dummy_update)

    # 1. AUTO Mode: Student currently IN -> should mark OUT
    student_in = {"id": "STU_001", "name": "Ananya Sharma", "current_status": "IN"}
    res1 = hostel_state.process_student_detection("STU_001", "CAM_01_ENTRY", student_in, camera_mode="AUTO")
    assert res1 == "OUT"

    # 2. AUTO Mode: Student currently OUT -> should mark IN
    student_out = {"id": "STU_002", "name": "Priya Verma", "current_status": "OUT"}
    res2 = hostel_state.process_student_detection("STU_002", "CAM_01_ENTRY", student_out, camera_mode="AUTO")
    assert res2 == "IN"

    # 3. Force IN Mode: Student currently OUT -> should mark IN
    student_out_2 = {"id": "STU_003", "name": "Riya Singh", "current_status": "OUT"}
    res3 = hostel_state.process_student_detection("STU_003", "CAM_01_ENTRY", student_out_2, camera_mode="IN")
    assert res3 == "IN"

    # 4. Force OUT Mode: Student currently IN -> should mark OUT
    student_in_2 = {"id": "STU_004", "name": "Kavita Gupta", "current_status": "IN"}
    res4 = hostel_state.process_student_detection("STU_004", "CAM_01_ENTRY", student_in_2, camera_mode="OUT")
    assert res4 == "OUT"


from src.utils.auth_helpers import generate_jwt_token

def test_camera_mode_api_endpoints(client):
    """Test GET and POST /hostel/api/camera_mode endpoints."""
    token = generate_jwt_token("warden-01", "warden@example.com", "warden", is_admin=True)
    client.set_cookie("jwt_access_token", token)

    # GET initial mode
    resp_get = client.get("/hostel/api/camera_mode")
    assert resp_get.status_code == 200
    data_get = resp_get.get_json()
    assert data_get["status"] == "success"
    assert "mode" in data_get
    assert "available_modes" in data_get

    # POST update to IN
    resp_post_in = client.post("/hostel/api/camera_mode", json={"mode": "IN"})
    assert resp_post_in.status_code == 200
    data_post_in = resp_post_in.get_json()
    assert data_post_in["status"] == "success"
    assert data_post_in["mode"] == "IN"

    # POST update to AUTO
    resp_post_auto = client.post("/hostel/api/camera_mode", json={"mode": "AUTO"})
    assert resp_post_auto.status_code == 200
    data_post_auto = resp_post_auto.get_json()
    assert data_post_auto["mode"] == "AUTO"

    # POST toggle
    resp_toggle = client.post("/hostel/api/camera_mode", json={"toggle": True})
    assert resp_toggle.status_code == 200
    assert resp_toggle.get_json()["mode"] == "IN"

    # POST invalid mode returns 400
    resp_invalid = client.post("/hostel/api/camera_mode", json={"mode": "INVALID"})
    assert resp_invalid.status_code == 400
