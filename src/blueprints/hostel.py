"""
Girls Hostel Management Blueprint — BioSecure AI.

Exposes warden control portal, student directory, movement logs,
and curfew overdue alert management endpoints under `/hostel`.
"""

import logging
import io
import datetime
import cv2
import numpy as np
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for, Response
from src.utils import hostel_db
from src.utils.face import model as face_model, normalize_embedding
from src.utils.face_cache import add_student_to_cache
from src.services.curfew_service import start_curfew_service
from src.services.hostel_camera import start_hostel_camera, get_camera_manager

logger = logging.getLogger(__name__)

hostel_bp = Blueprint("hostel", __name__, url_prefix="/hostel")

# Ensure background curfew scanner and camera recognition service are running
try:
    start_curfew_service()
except Exception as e:
    logger.warning(f"Could not start curfew monitoring service: {e}")

try:
    start_hostel_camera()
except Exception as e:
    logger.warning(f"Could not start hostel camera recognition service: {e}")

@hostel_bp.route("/")
def dashboard():
    """Render main Hostel Warden Control Center."""
    return render_template("hostel_dashboard.html")

@hostel_bp.route("/video_feed")
def video_feed():
    """
    Live MJPEG video stream from gate camera with face recognition overlay.
    Accepts optional query parameter ?role=IN or ?role=OUT (default: IN).
    """
    role = request.args.get("role", "IN").strip().upper()
    if role not in ("IN", "OUT"):
        role = "IN"
    camera_manager = get_camera_manager()
    return Response(
        camera_manager.generate_mjpeg_stream(role=role),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@hostel_bp.route("/video_feed/in")
def video_feed_in():
    """Dedicated endpoint for IN Gate live MJPEG feed."""
    return Response(
        get_camera_manager().generate_mjpeg_stream(role="IN"),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@hostel_bp.route("/video_feed/out")
def video_feed_out():
    """Dedicated endpoint for OUT Gate live MJPEG feed."""
    return Response(
        get_camera_manager().generate_mjpeg_stream(role="OUT"),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@hostel_bp.route("/video_frame")
def video_frame():
    """Return latest single JPEG frame from gate camera with face recognition overlay."""
    role = request.args.get("role", "IN").strip().upper()
    if role not in ("IN", "OUT"):
        role = "IN"
    camera_manager = get_camera_manager()
    jpeg_bytes = camera_manager.get_latest_jpeg(role=role)
    if not jpeg_bytes:
        from src.services.hostel_camera import _placeholder_bytes
        jpeg_bytes = _placeholder_bytes
    return Response(jpeg_bytes, mimetype="image/jpeg")

@hostel_bp.route("/students")
def students_page():
    """Render Hostel Student Directory & Registration Page."""
    return render_template("hostel_students.html")

@hostel_bp.route("/logs")
def logs_page():
    """Render Movement Logs History Page."""
    return render_template("hostel_logs.html")

@hostel_bp.route("/curfew")
def curfew_page():
    """Render Curfew Alerts & Schedule Management Page."""
    return render_template("hostel_curfew.html")

# ============================================================================
# API Endpoints
# ============================================================================

@hostel_bp.route("/api/stats")
def get_stats():
    """Return live summary statistics (Total IN, OUT, OVERDUE)."""
    try:
        students = hostel_db.fetch_all_hostel_students()
        total_in = sum(1 for s in students if s.get("current_status") == "IN")
        total_out = sum(1 for s in students if s.get("current_status") == "OUT")
        
        overdue_alerts = hostel_db.fetch_overdue_curfew_students()
        overdue_count = len(overdue_alerts)

        return jsonify({
            "total_students": len(students),
            "total_in": total_in,
            "total_out": total_out,
            "overdue_count": overdue_count,
            "curfew_window": "17:00 - 19:30"
        }), 200
    except Exception as e:
        logger.error(f"Error serving /api/stats: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/students")
def get_students_api():
    """Return list of enrolled hostel students."""
    try:
        students = hostel_db.fetch_all_hostel_students()
        return jsonify({"students": students}), 200
    except Exception as e:
        logger.error(f"Error fetching students: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/register_student", methods=["POST"])
def register_student_api():
    """
    Register a new student profile and extract 512D InsightFace ArcFace embedding
    from uploaded face photo into girls_hostel.student_profiles.
    """
    try:
        name = request.form.get("name")
        roll_number = request.form.get("roll_number")
        room_number = request.form.get("room_number")
        hostel_block = request.form.get("hostel_block", "Block-A")
        parent_contact = request.form.get("parent_contact")
        student_contact = request.form.get("student_contact", "")

        if not name or not roll_number or not room_number or not parent_contact:
            return jsonify({"error": "Name, Roll Number, Room Number, and Parent Contact are required."}), 400

        # Handle Face Photo & Embedding Extraction
        face_photo = request.files.get("face_photo")
        embedding_list = None

        if face_photo and face_photo.filename:
            file_bytes = face_photo.read()
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is not None:
                # Detect face with InsightFace buffalo_l
                faces = face_model.get(img)
                if len(faces) > 0:
                    raw_emb = faces[0].embedding
                    norm_emb = normalize_embedding(raw_emb)
                    if norm_emb is not None:
                        embedding_list = norm_emb.tolist()
                        logger.info(f"Successfully extracted 512D face embedding for {name} (Roll: {roll_number})")
                else:
                    logger.warning(f"No face detected in uploaded photo for {name}. Registering without face embedding.")

        # Get DB client — auto-falls back to in-memory mock if girls_hostel schema
        # is not yet exposed in Supabase (PGRST106). Data persists in mock until
        # Supabase is configured. See README for schema exposure steps.
        client = hostel_db.get_hostel_client()

        # Check if roll number already exists
        try:
            existing = client.table("student_profiles").select("id").eq("roll_number", roll_number).execute()
        except Exception as schema_err:
            if "PGRST106" in str(schema_err) or "Invalid schema" in str(schema_err):
                logger.warning("girls_hostel schema not exposed in Supabase yet — using local in-memory store.")
                client = hostel_db.get_mock_client()
                existing = client.table("student_profiles").select("id").eq("roll_number", roll_number).execute()
            else:
                raise

        if existing.data and len(existing.data) > 0:
            return jsonify({"error": f"Student with Roll Number '{roll_number}' is already enrolled."}), 400

        # Build payload
        payload = {
            "name": name,
            "roll_number": roll_number,
            "room_number": room_number,
            "hostel_block": hostel_block,
            "parent_contact": parent_contact,
            "student_contact": student_contact,
            "current_status": "IN"
        }
        if embedding_list:
            payload["embedding"] = embedding_list

        # Create record in girls_hostel.student_profiles
        try:
            res = client.table("student_profiles").insert(payload).execute()
        except Exception as insert_err:
            if "PGRST106" in str(insert_err) or "Invalid schema" in str(insert_err):
                logger.warning("Falling back to mock client for insert — girls_hostel schema not exposed.")
                client = hostel_db.get_mock_client()
                res = client.table("student_profiles").insert(payload).execute()
            else:
                raise

        if res.data and len(res.data) > 0 and embedding_list:
            new_id = res.data[0].get("id")
            # Update in-memory face cache
            add_student_to_cache(
                student_id=new_id,
                name=name,
                program="Hostel",
                branch=room_number,
                embedding=np.array(embedding_list, dtype=np.float32),
                roll_number=roll_number,
                room_number=room_number
            )

        msg = f"Student {name} enrolled successfully!"
        if not embedding_list and face_photo:
            msg += " (Note: No face detected in photo; please upload a clear frontal face image)"

        logger.info(f"Registered student profile '{name}' in girls_hostel schema.")
        return jsonify({"status": "success", "message": msg}), 200
    except Exception as e:
        logger.error(f"Error registering student: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/movement_logs")
def get_movement_logs():
    """Return recent student entry/exit logs."""
    try:
        limit = int(request.args.get("limit", 100))
        logs = hostel_db.fetch_recent_movement_logs(limit=limit)
        return jsonify({"logs": logs}), 200
    except Exception as e:
        logger.error(f"Error serving /api/movement_logs: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/overdue_alerts")
def get_overdue_alerts():
    """Return list of active overdue curfew alerts."""
    try:
        alerts = hostel_db.fetch_overdue_curfew_students()
        return jsonify({"alerts": alerts}), 200
    except Exception as e:
        logger.error(f"Error serving /api/overdue_alerts: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/resolve_alert", methods=["POST"])
def resolve_alert():
    """Manually resolve an overdue curfew alert."""
    try:
        data = request.get_json() or {}
        alert_id = data.get("alert_id")
        notes = data.get("notes", "Resolved by warden")

        if not alert_id:
            return jsonify({"error": "alert_id is required"}), 400

        client = hostel_db.get_hostel_client()
        client.table("curfew_alerts").update({
            "status": "RESOLVED",
            "resolved_at": "now()",
            "notes": notes
        }).eq("id", alert_id).execute()

        logger.info(f"Curfew alert {alert_id} resolved by warden.")
        return jsonify({"status": "success", "message": f"Alert {alert_id} resolved successfully"}), 200
    except Exception as e:
        logger.error(f"Error resolving alert: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/manual_entry", methods=["POST"])
def manual_entry_api():
    """
    Manually record student IN or OUT entry by warden.
    Accepts JSON or Form data with:
    - student_id: UUID of student
    - direction: 'IN' or 'OUT'
    - notes / remarks: Optional reason or notes
    """
    try:
        data = request.get_json(silent=True) or request.form or {}
        student_id = data.get("student_id")
        direction = data.get("direction")
        notes = data.get("notes") or data.get("remarks") or ""

        if not student_id:
            return jsonify({"error": "student_id is required"}), 400
        if not direction:
            return jsonify({"error": "direction ('IN' or 'OUT') is required"}), 400

        success, message, student = hostel_db.record_manual_movement(
            student_id=student_id,
            direction=direction,
            notes=notes,
            camera_id="MANUAL_ENTRY"
        )

        if not success:
            return jsonify({"error": message}), 400

        return jsonify({
            "status": "success",
            "message": message,
            "student": student
        }), 200
    except Exception as e:
        logger.error(f"Error processing manual entry API: {e}")
        return jsonify({"error": str(e)}), 500

@hostel_bp.route("/api/camera_mode", methods=["GET", "POST"])
def camera_mode_api():
    """Get or update current camera feed mode for local single webcam testing."""
    camera_mgr = get_camera_manager()
    if request.method == "POST":
        try:
            data = request.get_json(silent=True) or request.form or {}
            target_mode = data.get("mode")
            if not target_mode and data.get("toggle"):
                current = camera_mgr.get_camera_mode()
                cycle = {"AUTO": "IN", "IN": "OUT", "OUT": "DUAL", "DUAL": "AUTO"}
                target_mode = cycle.get(current, "AUTO")
            
            if not target_mode:
                return jsonify({"error": "Field 'mode' is required (e.g. 'AUTO', 'IN', 'OUT', 'DUAL')"}), 400
            
            new_mode = camera_mgr.set_camera_mode(target_mode)
            descriptions = {
                "AUTO": "Shared Webcam — Auto-Toggle (Smart In/Out based on student status)",
                "IN": "Shared Webcam — Force Entry Gate (IN)",
                "OUT": "Shared Webcam — Force Exit Gate (OUT)",
                "DUAL": "Dual Cameras — Independent Entry & Exit Gate Feeds"
            }
            return jsonify({
                "status": "success",
                "mode": new_mode,
                "description": descriptions.get(new_mode, new_mode),
                "message": f"Camera mode set to '{new_mode}' successfully"
            }), 200
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            logger.error(f"Error updating camera mode: {e}")
            return jsonify({"error": str(e)}), 500
    
    mode = camera_mgr.get_camera_mode()
    descriptions = {
        "AUTO": "Shared Webcam — Auto-Toggle (Smart In/Out based on student status)",
        "IN": "Shared Webcam — Force Entry Gate (IN)",
        "OUT": "Shared Webcam — Force Exit Gate (OUT)",
        "DUAL": "Dual Cameras — Independent Entry & Exit Gate Feeds"
    }
    return jsonify({
        "status": "success",
        "mode": mode,
        "description": descriptions.get(mode, mode),
        "available_modes": ["AUTO", "IN", "OUT", "DUAL"]
    }), 200
