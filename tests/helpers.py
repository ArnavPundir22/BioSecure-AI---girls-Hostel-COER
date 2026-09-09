"""
Helper utilities for E2E tests:
- High-precision 512D unit vector generation with exact calibrated cosine similarities
- Mock student generator and DB seeding helpers
- Synthetic camera stream frames
"""

import math
import random
from typing import Dict, List, Optional, Tuple
import numpy as np


def generate_unit_vector(dim: int = 512, seed: Optional[int] = None) -> List[float]:
    """Generate a random 512D unit-normalized vector (L2 norm = 1.0)."""
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()
    vec = rng.standard_normal(dim).astype(np.float64)
    norm = np.linalg.norm(vec)
    if norm == 0:
        vec[0] = 1.0
        norm = 1.0
    normalized = (vec / norm).tolist()
    return normalized


def generate_calibrated_vector_pair(
    similarity: float,
    dim: int = 512,
    seed: Optional[int] = None
) -> Tuple[List[float], List[float]]:
    """
    Generate two 512D unit vectors v1, v2 having exact mathematical cosine similarity s.
    Uses Gram-Schmidt orthogonalization:
        v2 = s * v1 + sqrt(1 - s^2) * v_perp
    """
    assert -1.0 <= similarity <= 1.0, "Cosine similarity must be in [-1.0, 1.0]"
    rng = np.random.default_rng(seed)

    # Base vector v1
    v1 = rng.standard_normal(dim).astype(np.float64)
    v1 = v1 / np.linalg.norm(v1)

    if math.isclose(similarity, 1.0, abs_tol=1e-7):
        return v1.tolist(), v1.tolist()
    if math.isclose(similarity, -1.0, abs_tol=1e-7):
        return v1.tolist(), (-v1).tolist()

    # Generate random vector w and make orthogonal to v1
    w = rng.standard_normal(dim).astype(np.float64)
    v_perp = w - np.dot(w, v1) * v1
    v_perp = v_perp / np.linalg.norm(v_perp)

    # Calibrate v2
    v2 = similarity * v1 + math.sqrt(max(0.0, 1.0 - similarity ** 2)) * v_perp
    v2 = v2 / np.linalg.norm(v2)

    return v1.tolist(), v2.tolist()


def generate_vector_with_similarity_to(
    base_vec: List[float],
    similarity: float,
    seed: Optional[int] = None
) -> List[float]:
    """Generate a unit vector having exact mathematical cosine similarity with base_vec."""
    assert -1.0 <= similarity <= 1.0
    v1 = np.array(base_vec, dtype=np.float64)
    v1 = v1 / np.linalg.norm(v1)

    if math.isclose(similarity, 1.0, abs_tol=1e-7):
        return v1.tolist()
    if math.isclose(similarity, -1.0, abs_tol=1e-7):
        return (-v1).tolist()

    rng = np.random.default_rng(seed)
    w = rng.standard_normal(len(base_vec)).astype(np.float64)
    v_perp = w - np.dot(w, v1) * v1
    v_perp = v_perp / np.linalg.norm(v_perp)

    v2 = similarity * v1 + math.sqrt(max(0.0, 1.0 - similarity ** 2)) * v_perp
    v2 = v2 / np.linalg.norm(v2)
    return v2.tolist()


def create_synthetic_frame(
    width: int = 640,
    height: int = 480,
    face_count: int = 1
) -> np.ndarray:
    """Create a synthetic BGR frame containing face_count synthetic face bounding patches."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Background texture
    frame[:] = (40, 40, 40)

    for i in range(face_count):
        # Draw distinct synthetic face boxes
        x = int(30 + (i * 55) % (width - 60))
        y = int(30 + ((i * 55) // (width - 60)) * 60)
        w, h = 45, 50
        if x + w < width and y + h < height:
            frame[y:y+h, x:x+w] = (200, 180, 150)  # Face tone
    return frame


def seed_test_student(
    mock_db,
    name: str = "Aanya Rao",
    roll_number: str = "GH-2026-001",
    room_number: str = "A-101",
    hostel_block: str = "Block-A",
    parent_contact: str = "+91-9876543210",
    student_contact: str = "+91-9876543211",
    current_status: str = "IN",
    embedding: Optional[List[float]] = None
) -> Dict:
    """Insert a test student into girls_hostel.student_profiles and return the record."""
    if embedding is None:
        embedding = generate_unit_vector(512)

    res = mock_db.table("student_profiles").insert({
        "name": name,
        "roll_number": roll_number,
        "room_number": room_number,
        "hostel_block": hostel_block,
        "parent_contact": parent_contact,
        "student_contact": student_contact,
        "current_status": current_status,
        "embedding": embedding
    }).execute()

    return res.data[0]
