"""
Curfew Monitoring & Overdue Alert Service — BioSecure AI.

Periodically evaluates student movement status against configured curfew hours.

Default:
    System Start Time: 5:00 PM (17:00)
    Curfew Deadline:   7:30 PM (19:30)

Flags overdue OUT students in `girls_hostel.curfew_alerts`.

Task 2:
    Prevent duplicate alerts for the same OUT movement/session while
    allowing a NEW alert after the student returns IN and goes OUT again.
"""

import logging
import threading
import time
from datetime import datetime, time as dtime

from src.utils import hostel_db

logger = logging.getLogger(__name__)

DEFAULT_START_TIME = dtime(17, 0, 0)
DEFAULT_CURFEW_END = dtime(19, 30, 0)
DEFAULT_MORNING_RESET = dtime(6, 0, 0)


# ============================================================================
# CURFEW CONFIGURATION
# ============================================================================

def get_curfew_config():
    """Return the current curfew configuration from system settings."""
    config = hostel_db.get_system_settings("curfew_schedule") or {}

    return {
        "start_time": config.get("start_time", "17:00"),
        "end_time": config.get("end_time", "19:30"),
        "enabled": bool(config.get("enabled", True)),
    }


def parse_config_time(value, fallback):
    """Convert HH:MM text into a datetime.time object."""
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return fallback


# ============================================================================
# BACKGROUND SERVICE
# ============================================================================

_curfew_thread = None
_stop_event = threading.Event()


# ============================================================================
# CURFEW ACTIVE CHECK
# ============================================================================

def is_curfew_active(current_time: dtime) -> bool:
    """Return True if within the configured curfew enforcement window."""

    config = get_curfew_config()

    if not config["enabled"]:
        return False

    curfew_end = parse_config_time(
        config["end_time"],
        DEFAULT_CURFEW_END,
    )

    return (
        current_time >= curfew_end
        or current_time < DEFAULT_MORNING_RESET
    )


# ============================================================================
# FIND CURRENT OUT MOVEMENT
# ============================================================================

def get_latest_out_movement(client, student_id):
    """
    Get the latest OUT movement for a student.

    This identifies the student's current OUT session.

    Example:

        17:00 OUT  -> movement A
        18:30 IN   -> movement B
        19:00 OUT  -> movement C

    If the student is currently OUT, movement C is the active session.
    """

    result = (
        client.table("movement_logs")
        .select("id, direction, timestamp, camera_id, notes")
        .eq("student_id", student_id)
        .eq("direction", "OUT")
        .order("timestamp", desc=True)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


# ============================================================================
# CHECK WHETHER THE OUT SESSION HAS ALREADY BEEN ALERTED
# ============================================================================

def alert_exists_for_movement(client, student_id, movement_id):
    """
    Check whether a curfew alert already exists for this exact OUT movement.

    This is the important Task 2 protection.

    We do NOT check only:
        student_id + date

    because a student can legitimately have multiple OUT movements
    during the same day.
    """

    # Preferred method:
    # store the movement ID in the alert's notes as a machine-readable
    # marker so this works without requiring an immediate database schema
    # change.

    marker = f"movement_id:{movement_id}"

    result = (
        client.table("curfew_alerts")
        .select("id, status, notes")
        .eq("student_id", student_id)
        .execute()
    )

    for alert in result.data or []:
        notes = alert.get("notes") or ""

        if marker in notes:
            return True

    return False


# ============================================================================
# CURFEW VIOLATION CHECK
# ============================================================================

def check_curfew_violations():
    """
    Query students who are currently OUT after curfew.

    Task 2 behavior:

        OUT
          ↓
        Curfew crossed
          ↓
        Create alert for current OUT movement
          ↓
        Scanner repeats
          ↓
        No duplicate
          ↓
        Warden resolves / adds notes
          ↓
        Still OUT
          ↓
        No duplicate
          ↓
        Student IN
          ↓
        Current OUT session ends
          ↓
        Student OUT again
          ↓
        New movement ID
          ↓
        New curfew alert allowed
    """

    now = datetime.now()
    current_time = now.time()

    if not is_curfew_active(current_time):
        return

    config = get_curfew_config()

    system_start_time = parse_config_time(
        config["start_time"],
        DEFAULT_START_TIME,
    )

    curfew_end_time = parse_config_time(
        config["end_time"],
        DEFAULT_CURFEW_END,
    )

    logger.info(
        "[Curfew Scanner] Evaluating curfew status at %s "
        "(deadline: %s)...",
        now.strftime("%H:%M:%S"),
        curfew_end_time.strftime("%H:%M"),
    )

    students = hostel_db.fetch_all_hostel_students()

    out_students = [
        student
        for student in students
        if student.get("current_status") == "OUT"
    ]

    if not out_students:
        logger.info(
            "[Curfew Scanner] All students are inside hostel. "
            "Zero curfew violations."
        )
        return

    logger.warning(
        "[Curfew Scanner] Found %d students currently OUT past "
        "%s curfew!",
        len(out_students),
        curfew_end_time.strftime("%I:%M %p").lstrip("0"),
    )

    client = hostel_db.get_hostel_client()

    today_str = now.date().isoformat()

    for student in out_students:

        student_id = student["id"]

        # ------------------------------------------------------------
        # Find the student's CURRENT OUT movement
        # ------------------------------------------------------------

        latest_out = get_latest_out_movement(
            client,
            student_id,
        )

        if not latest_out:
            logger.warning(
                "[Curfew Scanner] No OUT movement found for student %s. "
                "Skipping.",
                student_id,
            )
            continue

        movement_id = latest_out.get("id")

        if not movement_id:
            logger.warning(
                "[Curfew Scanner] OUT movement for student %s has no ID. "
                "Skipping.",
                student_id,
            )
            continue

        # ------------------------------------------------------------
        # TASK 2 — DUPLICATE ALERT PROTECTION
        # ------------------------------------------------------------

        if alert_exists_for_movement(
            client,
            student_id,
            movement_id,
        ):
            logger.info(
                "[Curfew Scanner] Alert already exists for student '%s' "
                "and OUT movement '%s'. Skipping duplicate.",
                student.get("name"),
                movement_id,
            )
            continue

        # ------------------------------------------------------------
        # CREATE NEW CURFEW ALERT
        # ------------------------------------------------------------

        alert_notes = (
            f"movement_id:{movement_id} | "
            f"OUT timestamp:{latest_out.get('timestamp')} | "
            f"Auto-generated curfew alert"
        )

        client.table("curfew_alerts").insert(
            {
                "student_id": student_id,
                "curfew_date": today_str,
                "system_start_time": system_start_time.strftime("%H:%M:%S"),
                "curfew_end_time": curfew_end_time.strftime("%H:%M:%S"),
                "status": "OVERDUE_OUT",
                "notes": alert_notes,
            }
        ).execute()

        logger.error(
            "🚨 CURFEW BREACH ALERT: Student '%s' "
            "(Roll: %s, Room: %s) is OUT past %s! "
            "Movement ID: %s | Parent: %s",
            student.get("name"),
            student.get("roll_number"),
            student.get("room_number"),
            curfew_end_time.strftime("%I:%M %p").lstrip("0"),
            movement_id,
            student.get("parent_contact"),
        )


# ============================================================================
# BACKGROUND LOOP
# ============================================================================

def _curfew_loop():
    """Background worker loop executing curfew check every 60 seconds."""

    logger.info("Curfew monitoring service thread started.")

    while not _stop_event.is_set():

        try:
            check_curfew_violations()

        except Exception as e:
            logger.error(
                "Error in curfew monitor loop: %s",
                e,
            )

        time.sleep(60)


def start_curfew_service():
    """Start background curfew scanner thread."""

    global _curfew_thread

    if _curfew_thread is None or not _curfew_thread.is_alive():

        _stop_event.clear()

        _curfew_thread = threading.Thread(
            target=_curfew_loop,
            daemon=True,
        )

        _curfew_thread.start()

        logger.info(
            "Curfew monitoring service initialised."
        )


def stop_curfew_service():
    """Stop background curfew scanner thread."""

    global _curfew_thread

    if _curfew_thread and _curfew_thread.is_alive():

        _stop_event.set()

        _curfew_thread.join(timeout=3)

        logger.info(
            "Curfew monitoring service stopped."
        )