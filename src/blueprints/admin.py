"""
Admin & CCTV Camera Management Blueprint — BioSecure AI.

Exposes administrative CCTV setup interface (/admin/cameras) and
camera settings API endpoints (/api/cameras/*).
"""

import copy
import logging
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for, g

from src.utils import hostel_db
from src.services import hostel_camera

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
cameras_api_bp = Blueprint("cameras_api", __name__, url_prefix="/api/cameras")


def _is_authenticated() -> bool:
    """Check if session or request context contains authenticated user."""
    return bool(session.get("logged_in") or getattr(g, "user", None))


@admin_bp.route("/cameras")
def admin_cameras():
    """Render the responsive CCTV Camera Setup Management UI."""
    if not _is_authenticated():
        return redirect(url_for("auth.login"))

    in_camera = hostel_db.get_camera_settings("IN") or {}
    out_camera = hostel_db.get_camera_settings("OUT") or {}
    return render_template(
        "admin_cameras.html",
        in_camera=in_camera,
        out_camera=out_camera,
        session_username=session.get("username", "Admin"),
        session_is_admin=session.get("is_admin", True)
    )


def _handle_get_camera_settings():
    """Return JSON representation of active camera configurations."""
    if not _is_authenticated():
        return jsonify({"error": "Authentication required", "success": False}), 401

    in_cam = hostel_db.get_camera_settings("IN") or {}
    out_cam = hostel_db.get_camera_settings("OUT") or {}

    in_cam_clean = copy.deepcopy(in_cam)
    out_cam_clean = copy.deepcopy(out_cam)

    if in_cam_clean.get("password"):
        in_cam_clean["password"] = "••••••••"
    if out_cam_clean.get("password"):
        out_cam_clean["password"] = "••••••••"

    in_cam_clean["rtsp_url"] = hostel_camera._mask_rtsp_url(hostel_db.build_rtsp_url(in_cam))
    out_cam_clean["rtsp_url"] = hostel_camera._mask_rtsp_url(hostel_db.build_rtsp_url(out_cam))

    return jsonify({
        "success": True,
        "cameras": {
            "IN": in_cam_clean,
            "OUT": out_cam_clean
        }
    }), 200


def _handle_test_connection():
    """Probe camera stream on-demand, measure metrics, and return preview thumbnail."""
    if not _is_authenticated():
        return jsonify({"error": "Authentication required", "success": False}), 401

    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict) or not data:
        return jsonify({
            "success": False,
            "status": "INVALID_REQUEST",
            "error": "No camera configuration provided in request body."
        }), 400

    result = hostel_camera.test_camera_connection(data)
    return jsonify(result), 200


def _handle_save_cameras():
    """Persist camera settings to girls_hostel.camera_settings and hot-reload stream workers."""
    if not _is_authenticated():
        return jsonify({"error": "Authentication required", "success": False}), 401

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"success": False, "error": "No configuration data provided."}), 400

    saved_roles = []
    if "cameras" in data and isinstance(data["cameras"], dict):
        targets = data["cameras"]
    elif "IN" in data or "OUT" in data:
        targets = data
    elif "camera_role" in data:
        targets = {data["camera_role"]: data}
    else:
        return jsonify({"success": False, "error": "Unrecognized camera configuration format."}), 400

    for role_key, conf in targets.items():
        role_norm = str(role_key).strip().upper()
        if role_norm in ("IN", "OUT") and isinstance(conf, dict):
            conf["camera_role"] = role_norm
            ok = hostel_db.save_camera_settings(role_norm, conf)
            if ok:
                saved_roles.append(role_norm)

    if not saved_roles:
        return jsonify({"success": False, "error": "Failed to save camera settings to database."}), 500

    # Hot-reload background camera streaming workers
    try:
        hostel_camera.get_camera_manager().reload_camera_configurations()
    except Exception as e:
        logger.warning(f"Could not reload camera manager configurations: {e}")

    return jsonify({
        "success": True,
        "message": f"Successfully updated camera settings for: {', '.join(saved_roles)}",
        "saved_roles": saved_roles
    }), 200


# Register API routes on cameras_api_bp (/api/cameras/*)
@cameras_api_bp.route("/settings", methods=["GET"])
def api_cameras_settings():
    return _handle_get_camera_settings()


@cameras_api_bp.route("/test-connection", methods=["POST"])
def api_cameras_test_connection():
    return _handle_test_connection()


@cameras_api_bp.route("/save", methods=["POST"])
def api_cameras_save():
    return _handle_save_cameras()


# Register identical alias routes on admin_bp (/admin/api/cameras/* and /admin/cameras/*)
@admin_bp.route("/api/cameras/settings", methods=["GET"])
@admin_bp.route("/cameras/settings", methods=["GET"])
def admin_api_cameras_settings():
    return _handle_get_camera_settings()


@admin_bp.route("/api/cameras/test-connection", methods=["POST"])
@admin_bp.route("/cameras/test-connection", methods=["POST"])
def admin_api_cameras_test_connection():
    return _handle_test_connection()


@admin_bp.route("/api/cameras/save", methods=["POST"])
@admin_bp.route("/cameras/save", methods=["POST"])
def admin_api_cameras_save():
    return _handle_save_cameras()
