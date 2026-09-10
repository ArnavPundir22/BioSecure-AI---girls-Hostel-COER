"""
Hostel Movement State Machine & Anti-Bounce Cooldown Manager — BioSecure AI.

Handles directional movement state transitions (IN <-> OUT) and suppresses
duplicate reads when a face lingers in front of the camera.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional, Any
from src.utils import hostel_db

logger = logging.getLogger(__name__)

# Anti-bounce cooldown setting (seconds)
COOLDOWN_SECONDS: int = 15

# In-memory cooldown cache: { student_id: (camera_id, last_event_timestamp) }
_cooldown_registry: Dict[Any, Any] = {}
_cooldown_lock = threading.Lock()

def process_student_detection(student_id: str, camera_id: str, student_info: dict) -> Optional[str]:
    """
    Process a detected student face on a given camera.
    Returns: 'IN', 'OUT', or None (if skipped due to cooldown).
    """
    now = datetime.now(timezone.utc)
    
    # 1. Thread-safe anti-bounce cooldown check & optimistic pre-reservation
    with _cooldown_lock:
        cooldown_time = _cooldown_registry.get((student_id, camera_id))
        if cooldown_time is not None:
            time_elapsed = (now - cooldown_time).total_seconds()
            if time_elapsed < COOLDOWN_SECONDS:
                logger.debug(f"Cooldown active for student {student_id} on {camera_id} ({time_elapsed:.1f}s elapsed). Skipping.")
                return None
        elif student_id in _cooldown_registry:
            reg_val = _cooldown_registry[student_id]
            if isinstance(reg_val, tuple) and len(reg_val) == 2:
                last_cam, last_time = reg_val
                time_elapsed = (now - last_time).total_seconds()
                if last_cam == camera_id and time_elapsed < COOLDOWN_SECONDS:
                    logger.debug(f"Cooldown active for student {student_id} on {camera_id} ({time_elapsed:.1f}s elapsed). Skipping.")
                    return None

        # Optimistically pre-reserve cooldown slot before database transaction
        prior_pair = _cooldown_registry.get((student_id, camera_id))
        prior_single = _cooldown_registry.get(student_id)
        _cooldown_registry[(student_id, camera_id)] = now
        _cooldown_registry[student_id] = (camera_id, now)

    # 2. Determine target direction based on camera ID
    # Camera 01 (Entry) -> IN
    # Camera 02 (Exit)  -> OUT
    if "ENTRY" in camera_id.upper() or camera_id == "CAM_01_ENTRY":
        target_direction = "IN"
    elif "EXIT" in camera_id.upper() or camera_id == "CAM_02_EXIT":
        target_direction = "OUT"
    else:
        logger.warning(f"Unknown camera_id: {camera_id}. Defaulting direction based on current status.")
        current_status = student_info.get("current_status", "IN")
        target_direction = "OUT" if current_status == "IN" else "IN"

    # 2b. Debounce if student is already in target state (e.g. loitering past gate)
    current_status = student_info.get("current_status")
    if current_status == target_direction:
        logger.debug(f"Student {student_id} already in state '{target_direction}'. Debouncing state transition.")
        return target_direction

    # 3. Update status in isolated database
    success = False
    try:
        success = hostel_db.update_student_movement_state(
            student_id=student_id,
            direction=target_direction,
            camera_id=camera_id
        )
    except Exception as e:
        logger.error(f"Failed to update movement state for student {student_id}: {e}")
        success = False

    if success:
        logger.info(f"State updated: Student '{student_info.get('name')}' marked {target_direction} via {camera_id}")
        return target_direction
    
    # 4. Revert optimistic cooldown reservation if database transaction failed
    with _cooldown_lock:
        if prior_pair is not None:
            _cooldown_registry[(student_id, camera_id)] = prior_pair
        else:
            _cooldown_registry.pop((student_id, camera_id), None)

        if prior_single is not None:
            _cooldown_registry[student_id] = prior_single
        else:
            _cooldown_registry.pop(student_id, None)

    return None
