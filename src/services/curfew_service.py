"""
Curfew Monitoring & Overdue Alert Service — BioSecure AI.

Periodically evaluates student movement status against configured curfew hours:
  System Start Time: 5:00 PM (17:00)
  Curfew Deadline:   7:30 PM (19:30)

Flags overdue OUT students in `girls_hostel.curfew_alerts` and dispatches alerts.
"""

import logging
import time
from datetime import datetime, time as dtime, timezone
import threading
from src.utils import hostel_db

logger = logging.getLogger(__name__)

# Default Curfew Bounds
DEFAULT_START_TIME = dtime(17, 0, 0)  # 5:00 PM
DEFAULT_CURFEW_END = dtime(19, 30, 0) # 7:30 PM
DEFAULT_MORNING_RESET = dtime(6, 0, 0) # 6:00 AM

_curfew_thread: threading.Thread = None
_stop_event = threading.Event()

def is_curfew_active(current_time: dtime) -> bool:
    """Return True if within curfew enforcement window (19:30 to 06:00 next morning)."""
    return current_time >= DEFAULT_CURFEW_END or current_time < DEFAULT_MORNING_RESET

def check_curfew_violations():
    """
    Query girls_hostel.student_profiles for students who are currently OUT past curfew end time.
    """
    now = datetime.now()
    current_time = now.time()

    # Check if current time is within active curfew enforcement window (19:30 - 06:00)
    if is_curfew_active(current_time):
        logger.info(f"[Curfew Scanner] Evaluating curfew status at {now.strftime('%H:%M:%S')}...")
        
        # Fetch all students whose status is 'OUT'
        students = hostel_db.fetch_all_hostel_students()
        out_students = [s for s in students if s.get("current_status") == "OUT"]

        if not out_students:
            logger.info("[Curfew Scanner] All students are inside hostel. Zero curfew violations.")
            return

        logger.warning(f"[Curfew Scanner] Found {len(out_students)} students currently OUT past 7:30 PM curfew!")
        
        client = hostel_db.get_hostel_client()
        today_str = now.date().isoformat()

        for s in out_students:
            student_id = s["id"]
            # Check if active alert already logged today
            existing = client.table("curfew_alerts") \
                .select("id") \
                .eq("student_id", student_id) \
                .eq("curfew_date", today_str) \
                .eq("status", "OVERDUE_OUT") \
                .execute()

            if not existing.data:
                # Create overdue alert entry
                client.table("curfew_alerts").insert({
                    "student_id": student_id,
                    "curfew_date": today_str,
                    "system_start_time": "17:00:00",
                    "curfew_end_time": "19:30:00",
                    "status": "OVERDUE_OUT"
                }).execute()
                
                logger.error(
                    f"🚨 CURFEW BREACH ALERT: Student '{s.get('name')}' (Roll: {s.get('roll_number')}, "
                    f"Room: {s.get('room_number')}) is OUT past 7:30 PM! Parent: {s.get('parent_contact')}"
                )

def _curfew_loop():
    """Background worker loop executing curfew check every 60 seconds."""
    logger.info("Curfew monitoring service thread started.")
    while not _stop_event.is_set():
        try:
            check_curfew_violations()
        except Exception as e:
            logger.error(f"Error in curfew monitor loop: {e}")
        time.sleep(60)

def start_curfew_service():
    """Start background curfew scanner thread."""
    global _curfew_thread
    if _curfew_thread is None or not _curfew_thread.is_alive():
        _stop_event.clear()
        _curfew_thread = threading.Thread(target=_curfew_loop, daemon=True)
        _curfew_thread.start()
        logger.info("Curfew monitoring service initialised.")

def stop_curfew_service():
    """Stop background curfew scanner thread."""
    global _curfew_thread
    if _curfew_thread and _curfew_thread.is_alive():
        _stop_event.set()
        _curfew_thread.join(timeout=3)
        logger.info("Curfew monitoring service stopped.")
