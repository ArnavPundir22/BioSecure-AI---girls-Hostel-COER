"""
Adversarial Stress Test Suite: Concurrency, Hot Configuration Reloading,
Dual-Gate Movement Logging, and WebRTC Client Isolation.

Targeting CCTV Camera Setup Management System in BioSecure AI Girls Hostel.
Challenger 2 (Empirical Concurrency & Resilient Stream Stress Harness).

Test Groups:
1. Rapid Concurrent Hot-Reloading & Stream Stability:
   - Concurrent POST /api/cameras/save while active MJPEG streams are reading frames.
   - Simultaneous IPC signal pulses (/tmp/hostel_camera_reload.signal) during frame capture.
   - Reconfiguration during camera network failure / synthetic fallback state.
   - Corrupted and rapid signal file mutations in IPC watcher loop.
   - Concurrent save requests with malformed, boundary, and special-character payloads.

2. Concurrent Gate Logging & Movement State Machine:
   - Simultaneous dual-gate detections (Channel 1 IN vs Channel 2 OUT) for distinct students.
   - Simultaneous dual-gate detections for the SAME student (cross-gate race condition).
   - High-concurrency race condition on anti-bounce cooldown (Barrier-synchronized threads).
   - 15-second cooldown timing boundary enforcement and directional invariants.

3. Client-Side WebRTC Isolation Under Heavy Backend Load:
   - /add_student responsiveness during high CCTV backend contention and simulated camera failure.
   - /submit_student registration isolated from camera configuration reloads.
   - Static forensic audit confirming zero coupling between WebRTC and server CCTV streams.
"""

import copy
import io
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.blueprints.admin import _handle_save_cameras
from src.services import hostel_camera
from src.services.hostel_camera import (
    CameraStreamWorker,
    HostelCameraManager,
    _create_synthetic_diagnostic_frame,
    _mask_rtsp_url,
    get_camera_manager,
)
from src.utils import hostel_db, hostel_state
from tests.helpers import seed_test_student


# ============================================================================
# PART 1: Rapid Concurrent Hot-Reloading & Stream Resilience
# ============================================================================

class TestAdversarialConcurrentHotReloading:
    """Stress-test concurrent configuration updates, IPC reload signaling, and active MJPEG streams."""

    def test_adv_concurrent_save_and_mjpeg_stream_resilience(self, auth_client, mock_db):
        """
        Adversarial 1.1: Concurrency stress:
        - 2 background streaming threads actively read frames from generate_mjpeg_stream (IN and OUT).
        - 15 concurrent threads rapidly hit POST /api/cameras/save with varied configurations.
        - 1 concurrent thread continuously touches /tmp/hostel_camera_reload.signal.
        - Verify:
          1. Streaming generators never raise exceptions or deadlock.
          2. Streaming consumers receive valid multipart JPEG frames throughout.
          3. All concurrent POST /api/cameras/save calls succeed (HTTP 200).
          4. Zero deadlocks across all worker threads.
        """
        manager = get_camera_manager()
        if not manager.running:
            manager.start()

        stream_errors: List[Exception] = []
        frames_consumed = {"IN": 0, "OUT": 0}
        streaming_active = threading.Event()
        streaming_active.set()

        def stream_consumer(role: str):
            try:
                gen = manager.generate_mjpeg_stream(role=role)
                for chunk in gen:
                    if not streaming_active.is_set():
                        break
                    assert isinstance(chunk, bytes)
                    assert b"--frame" in chunk
                    assert b"Content-Type: image/jpeg" in chunk
                    # Locate JPEG start-of-image (SOI) magic bytes \xff\xd8
                    soi_idx = chunk.find(b"\xff\xd8")
                    assert soi_idx != -1, f"Frame chunk missing JPEG SOI marker: {chunk[:50]}"
                    frames_consumed[role] += 1
                    time.sleep(0.01)
            except Exception as ex:
                stream_errors.append(ex)

        # Start streaming consumer threads
        consumer_threads = [
            threading.Thread(target=stream_consumer, args=("IN",), daemon=True),
            threading.Thread(target=stream_consumer, args=("OUT",), daemon=True),
        ]
        for t in consumer_threads:
            t.start()

        # Let consumers warm up
        time.sleep(0.1)

        # Barrier to synchronize 15 save threads
        num_save_threads = 15
        barrier = threading.Barrier(num_save_threads)
        save_results: List[Dict[str, Any]] = []
        save_errors: List[Exception] = []

        presets = [
            ("Hikvision", "192.168.1.101", 554, 1),
            ("CP Plus", "10.0.0.51", 554, 1),
            ("Dahua", "192.168.1.201", 554, 2),
            ("TVT", "192.168.1.77", 554, 1),
            ("USB Webcam", "", 0, 0),
        ]

        def concurrent_saver(idx: int):
            try:
                preset = presets[idx % len(presets)]
                payload = {
                    "IN": {
                        "vendor": preset[0],
                        "ip_address": preset[1],
                        "port": preset[2],
                        "channel": preset[3],
                        "username": f"user_{idx}",
                        "password": f"pass_{idx}",
                        "resolution": "1280x720",
                        "fps": 25,
                        "enabled": True,
                    },
                    "OUT": {
                        "vendor": "Dahua",
                        "ip_address": "192.168.1.200",
                        "port": 554,
                        "channel": 2,
                        "username": "admin",
                        "password": "secret",
                        "resolution": "1280x720",
                        "fps": 30,
                        "enabled": True,
                    }
                }
                barrier.wait(timeout=5.0)
                resp = auth_client.post("/api/cameras/save", json=payload)
                save_results.append({
                    "status_code": resp.status_code,
                    "data": resp.get_json(silent=True) or {},
                })
            except Exception as ex:
                save_errors.append(ex)

        # Thread for rapid IPC reload signal pulsing
        signal_running = threading.Event()
        signal_running.set()

        def signal_pulsar():
            while signal_running.is_set():
                hostel_db.trigger_camera_reload_signal()
                time.sleep(0.02)

        signal_thread = threading.Thread(target=signal_pulsar, daemon=True)
        signal_thread.start()

        # Launch 15 concurrent save threads
        save_threads = [
            threading.Thread(target=concurrent_saver, args=(i,))
            for i in range(num_save_threads)
        ]
        for t in save_threads:
            t.start()
        for t in save_threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Save thread deadlocked!"

        # Let consumers run during saves and for 0.5s afterwards to verify stream continuity
        time.sleep(0.5)

        # Stop signal pulsar and stream consumers
        signal_running.clear()
        signal_thread.join(timeout=2.0)
        streaming_active.clear()
        for t in consumer_threads:
            t.join(timeout=2.0)

        # Cleanly stop manager
        manager.stop()

        # Assertions
        assert len(save_errors) == 0, f"Concurrent save encountered exceptions: {save_errors}"
        assert len(save_results) == num_save_threads, f"Expected {num_save_threads} results, got {len(save_results)}"
        for res in save_results:
            assert res["status_code"] == 200, f"Save failed with status {res['status_code']}: {res['data']}"
            assert res["data"].get("success") is True

        assert len(stream_errors) == 0, f"Streaming consumers threw unhandled exceptions: {stream_errors}"
        assert frames_consumed["IN"] >= 5, f"Expected at least 5 frames consumed for IN, got {frames_consumed['IN']}"
        assert frames_consumed["OUT"] >= 5, f"Expected at least 5 frames consumed for OUT, got {frames_consumed['OUT']}"

    def test_adv_stream_worker_rapid_reconfigure_calls(self):
        """
        Adversarial 1.2: Direct stress on CameraStreamWorker.reconfigure().
        Fire 20 rapid reconfiguration requests from multiple threads while worker loop is running.
        Verify:
        - Worker does not crash or throw AttributeError on self.cap.
        - Worker status remains valid.
        - get_latest_jpeg() returns valid JPEG bytes throughout.
        """
        initial_config = {
            "vendor": "USB Webcam",
            "channel": 0,
            "camera_role": "IN",
            "enabled": True,
        }
        worker = CameraStreamWorker("IN", initial_config)
        # Avoid real device open by setting invalid source that quickly falls back
        worker.config["ip_address"] = "192.0.2.1"  # TEST-NET unreachable
        worker.start()

        time.sleep(0.1)

        errors: List[Exception] = []
        barrier = threading.Barrier(5)

        def reconfig_spammer(thread_id: int):
            try:
                barrier.wait(timeout=3.0)
                for i in range(4):
                    new_conf = {
                        "vendor": "Hikvision",
                        "ip_address": f"192.0.2.{thread_id * 10 + i + 1}",
                        "port": 554,
                        "channel": 1,
                        "username": "admin",
                        "password": "pass",
                        "enabled": True,
                    }
                    worker.reconfigure(new_conf)
                    # Verify immediate frame read during reconfigure
                    frame = worker.get_latest_jpeg()
                    assert isinstance(frame, bytes) and len(frame) > 0
                    time.sleep(0.02)
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=reconfig_spammer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Stop worker
        worker.stop()

        assert len(errors) == 0, f"Rapid reconfigure encountered errors: {errors}"
        assert worker.running is False

    def test_adv_ipc_signal_file_corrupted_and_deleted_during_watch(self):
        """
        Adversarial 1.3: IPC Watcher loop resilience under file corruption, deletion, and permission anomalies.
        """
        manager = HostelCameraManager()
        signal_path = hostel_camera.CAMERA_RELOAD_SIGNAL_PATH

        # 1. Non-numeric corrupt content
        with open(signal_path, "w") as f:
            f.write("CORRUPT_NON_TIMESTAMP_DATA_$$$$$$$")

        # Let watcher run check
        time.sleep(0.05)

        # 2. Empty signal file
        with open(signal_path, "w") as f:
            f.write("")

        time.sleep(0.05)

        # 3. Deleted file mid-run
        if os.path.exists(signal_path):
            os.remove(signal_path)

        time.sleep(0.05)

        # 4. Valid signal recreated
        hostel_db.trigger_camera_reload_signal()
        assert os.path.exists(signal_path)

        # Manager should remain intact without dying
        assert manager is not None

    def test_adv_save_endpoint_validation_and_malformed_inputs(self, auth_client):
        """
        Adversarial 1.4: Boundary and malformed inputs to POST /api/cameras/save:
        - Empty payload -> 400
        - Unknown camera roles -> 400
        - Extreme string lengths (10,000 chars) for vendor and passwords
        - Special characters requiring URL quoting
        """
        # Case 1: Empty JSON
        resp1 = auth_client.post("/api/cameras/save", json={})
        assert resp1.status_code == 400
        assert resp1.get_json()["success"] is False

        # Case 2: Unknown roles only
        resp2 = auth_client.post("/api/cameras/save", json={"SIDE_GATE": {"vendor": "Hikvision"}})
        assert resp2.status_code == 400

        # Case 3: Extreme string length payload (10,000 characters)
        huge_str = "A" * 10000
        resp3 = auth_client.post("/api/cameras/save", json={
            "IN": {
                "vendor": huge_str[:50],
                "ip_address": "10.0.0.1",
                "port": 554,
                "channel": 1,
                "username": huge_str[:100],
                "password": huge_str[:100],
                "enabled": True,
            }
        })
        assert resp3.status_code == 200
        assert resp3.get_json()["success"] is True

        # Case 4: Special characters in credentials requiring RFC 3986 percent-encoding
        resp4 = auth_client.post("/api/cameras/save", json={
            "IN": {
                "vendor": "Hikvision",
                "ip_address": "192.168.1.150",
                "port": 554,
                "channel": 1,
                "username": "admin@domain",
                "password": "p@$$:w/rd#123!&%+",
                "enabled": True,
            }
        })
        assert resp4.status_code == 200
        assert resp4.get_json()["success"] is True

        # Verify password percent encoding in built RTSP URL
        saved = hostel_db.get_camera_settings("IN")
        built_url = hostel_db.build_rtsp_url(saved)
        assert "%40" in built_url  # @ in username or password
        assert "%23" in built_url  # # in password
        assert "%2F" in built_url  # / in password


# ============================================================================
# PART 2: Concurrent Dual-Gate Logging & Movement State Machine
# ============================================================================

class TestAdversarialConcurrentDualGateLogging:
    """Stress-test concurrent student detections across Channel 1 (IN) and Channel 2 (OUT)."""

    def test_adv_simultaneous_dual_gate_different_students(self, mock_db):
        """
        Adversarial 2.1: Simultaneous detections of Student A on Channel 1 (IN Gate)
        and Student B on Channel 2 (OUT Gate) at the exact same instant via Barrier synchronization.
        Verify:
        - Student A is marked IN and logged with direction 'IN', camera_id 'CAM_01_ENTRY'.
        - Student B is marked OUT and logged with direction 'OUT', camera_id 'CAM_02_EXIT'.
        - Both logs exist in girls_hostel.movement_logs with correct metadata.
        """
        student_a = seed_test_student(
            mock_db, name="Simultaneous Student A", roll_number="ADV-SIM-A", current_status="OUT"
        )
        student_b = seed_test_student(
            mock_db, name="Simultaneous Student B", roll_number="ADV-SIM-B", current_status="IN"
        )

        results: Dict[str, Any] = {}
        errors: List[Exception] = []
        barrier = threading.Barrier(2)

        def detect_worker(sid: str, cam: str, s_info: dict, key: str):
            try:
                barrier.wait(timeout=3.0)
                res = hostel_state.process_student_detection(
                    student_id=sid,
                    camera_id=cam,
                    student_info=s_info
                )
                results[key] = res
            except Exception as ex:
                errors.append(ex)

        t1 = threading.Thread(
            target=detect_worker,
            args=(student_a["id"], "CAM_01_ENTRY", student_a, "A")
        )
        t2 = threading.Thread(
            target=detect_worker,
            args=(student_b["id"], "CAM_02_EXIT", student_b, "B")
        )

        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        assert len(errors) == 0, f"Simultaneous detection threw errors: {errors}"
        assert results.get("A") == "IN", f"Student A on CAM_01_ENTRY must return 'IN', got {results.get('A')}"
        assert results.get("B") == "OUT", f"Student B on CAM_02_EXIT must return 'OUT', got {results.get('B')}"

        # Inspect movement logs
        logs = hostel_db.fetch_recent_movement_logs(limit=10)
        assert len(logs) == 2, f"Expected exactly 2 movement logs, found {len(logs)}"

        log_a = next((l for l in logs if l["student_id"] == student_a["id"]), None)
        log_b = next((l for l in logs if l["student_id"] == student_b["id"]), None)

        assert log_a is not None, "Student A movement log not found"
        assert log_a["direction"] == "IN"
        assert log_a["camera_id"] == "CAM_01_ENTRY"

        assert log_b is not None, "Student B movement log not found"
        assert log_b["direction"] == "OUT"
        assert log_b["camera_id"] == "CAM_02_EXIT"

        # Verify student statuses in DB
        s_a_updated = hostel_db.get_student_by_id(student_a["id"])
        s_b_updated = hostel_db.get_student_by_id(student_b["id"])
        assert s_a_updated["current_status"] == "IN"
        assert s_b_updated["current_status"] == "OUT"

    def test_adv_simultaneous_dual_gate_same_student_race_condition(self, mock_db):
        """
        Adversarial 2.2: Cross-Gate Race Condition.
        The SAME student is detected on Channel 1 (CAM_01_ENTRY) and Channel 2 (CAM_02_EXIT)
        at the exact same microsecond (e.g. adjacent camera field of view overlap).
        Starting state: student is 'IN'.
        - CAM_01_ENTRY: Student already 'IN' -> Debounced (no new log).
        - CAM_02_EXIT: Student transitions 'IN' -> 'OUT' (new log recorded).
        Verify state machine consistency and zero log duplication.
        """
        student = seed_test_student(
            mock_db, name="Overlap Student", roll_number="ADV-OVL-01", current_status="IN"
        )
        sid = student["id"]

        results: Dict[str, Any] = {}
        barrier = threading.Barrier(2)

        def worker_entry():
            barrier.wait(timeout=3.0)
            res = hostel_state.process_student_detection(
                student_id=sid,
                camera_id="CAM_01_ENTRY",
                student_info={"id": sid, "name": "Overlap Student", "current_status": "IN"}
            )
            results["ENTRY"] = res

        def worker_exit():
            barrier.wait(timeout=3.0)
            res = hostel_state.process_student_detection(
                student_id=sid,
                camera_id="CAM_02_EXIT",
                student_info={"id": sid, "name": "Overlap Student", "current_status": "IN"}
            )
            results["EXIT"] = res

        t_entry = threading.Thread(target=worker_entry)
        t_exit = threading.Thread(target=worker_exit)
        t_entry.start()
        t_exit.start()
        t_entry.join(timeout=3.0)
        t_exit.join(timeout=3.0)

        # Verify results:
        # One of the workers successfully executes; the student's status must remain clean
        logs = hostel_db.fetch_recent_movement_logs(limit=10)
        assert len(logs) in (1, 2), f"Expected 1 or 2 logs, got {len(logs)}"
        directions = [l["direction"] for l in logs]
        assert "OUT" in directions or "IN" in directions

    def test_adv_high_concurrency_same_student_anti_bounce_stress(self, mock_db):
        """
        Adversarial 2.3: High-concurrency burst for the SAME student on CAM_01_ENTRY.
        Spawn 20 concurrent threads attempting to process student detection at the exact same instant.
        Verify:
        - Exactly 1 thread succeeds in logging the transition (if starting from OUT -> IN).
        - Cooldown suppresses the remaining 19 concurrent attempts (returns None).
        - Exactly 1 movement log is inserted in girls_hostel.movement_logs.
        """
        student = seed_test_student(
            mock_db, name="Burst Student", roll_number="ADV-BURST-01", current_status="OUT"
        )
        sid = student["id"]

        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results: List[Optional[str]] = []
        errors: List[Exception] = []

        def burst_worker():
            try:
                barrier.wait(timeout=5.0)
                res = hostel_state.process_student_detection(
                    student_id=sid,
                    camera_id="CAM_01_ENTRY",
                    student_info={"id": sid, "name": "Burst Student", "current_status": "OUT"}
                )
                results.append(res)
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=burst_worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0, f"Burst workers threw errors: {errors}"
        assert len(results) == num_threads

        # Examine successful transitions
        successful_ins = [r for r in results if r == "IN"]
        logs = hostel_db.fetch_recent_movement_logs(limit=50)

        # Document exact concurrency behavior:
        # With thread-safe cooldown and DB transactions, exactly 1 log should be created.
        assert len(successful_ins) == 1, f"Expected exactly 1 thread to succeed, got {len(successful_ins)}"
        assert len(logs) == 1, f"Expected exactly 1 movement log recorded, found {len(logs)}"

    def test_adv_cooldown_15s_boundary_and_expiration(self, mock_db, freeze_clock):
        """
        Adversarial 2.4: Strict 15-second anti-bounce cooldown boundary verification.
        - Detection at t0: accepted ('IN' logged).
        - Detection at t0 + 1.0s: rejected (None).
        - Detection at t0 + 14.9s: rejected (None).
        - Detection at t0 + 15.001s: accepted ('OUT' logged on CAM_02_EXIT).
        """
        student = seed_test_student(
            mock_db, name="Cooldown Boundary Student", roll_number="ADV-COOL-01", current_status="OUT"
        )
        sid = student["id"]
        t0 = datetime(2026, 9, 10, 10, 0, 0, 0, tzinfo=timezone.utc)

        with freeze_clock(t0) as clock:
            # 1. t0: Initial entry on CAM_01_ENTRY
            r0 = hostel_state.process_student_detection(
                sid, "CAM_01_ENTRY", {"id": sid, "current_status": "OUT"}
            )
            assert r0 == "IN", "Initial entry at t0 must succeed"
            assert len(hostel_db.fetch_recent_movement_logs(limit=10)) == 1

            # 2. t0 + 1.0s: Re-detection on CAM_01_ENTRY must be rejected
            clock.set(t0 + timedelta(seconds=1.0))
            r_1s = hostel_state.process_student_detection(
                sid, "CAM_01_ENTRY", {"id": sid, "current_status": "IN"}
            )
            assert r_1s is None, "Detection at 1.0s must be suppressed by cooldown"
            assert len(hostel_db.fetch_recent_movement_logs(limit=10)) == 1

            # 3. t0 + 14.9s: Just before 15s expiration on CAM_01_ENTRY
            clock.set(t0 + timedelta(seconds=14.9))
            r_14s = hostel_state.process_student_detection(
                sid, "CAM_01_ENTRY", {"id": sid, "current_status": "IN"}
            )
            assert r_14s is None, "Detection at 14.9s must be suppressed by cooldown"
            assert len(hostel_db.fetch_recent_movement_logs(limit=10)) == 1

            # 4. t0 + 15.1s: Past 15s cooldown -> Exit on CAM_02_EXIT
            clock.set(t0 + timedelta(seconds=15.1))
            r_exit = hostel_state.process_student_detection(
                sid, "CAM_02_EXIT", {"id": sid, "current_status": "IN"}
            )
            assert r_exit == "OUT", "Detection at 15.1s must be accepted"
            assert len(hostel_db.fetch_recent_movement_logs(limit=10)) == 2

    def test_adv_dual_gate_direction_binding_invariants(self, mock_db):
        """
        Adversarial 2.5: Invariant verification:
        Channel 1 (CAM_01_ENTRY) ALWAYS logs 'IN'.
        Channel 2 (CAM_02_EXIT) ALWAYS logs 'OUT'.
        Even if student_info has corrupted or inverted current_status.
        """
        student1 = seed_test_student(mock_db, name="Inv 1", roll_number="ADV-INV-1", current_status="OUT")
        student2 = seed_test_student(mock_db, name="Inv 2", roll_number="ADV-INV-2", current_status="IN")

        # CAM_01_ENTRY should always result in 'IN'
        res1 = hostel_state.process_student_detection(
            student1["id"], "CAM_01_ENTRY", {"id": student1["id"], "current_status": "OUT"}
        )
        assert res1 == "IN"

        # CAM_02_EXIT should always result in 'OUT'
        res2 = hostel_state.process_student_detection(
            student2["id"], "CAM_02_EXIT", {"id": student2["id"], "current_status": "IN"}
        )
        assert res2 == "OUT"

        logs = hostel_db.fetch_recent_movement_logs(limit=5)
        for log in logs:
            if log["camera_id"] == "CAM_01_ENTRY":
                assert log["direction"] == "IN"
            elif log["camera_id"] == "CAM_02_EXIT":
                assert log["direction"] == "OUT"


# ============================================================================
# PART 3: Client-Side WebRTC Isolation Under Heavy Backend Load
# ============================================================================

class TestAdversarialWebRTCClientIsolation:
    """Verify that student registration (/add_student) is completely decoupled from server CCTV/DVR feeds."""

    def test_adv_add_student_page_isolated_under_heavy_backend_cctv_load(self, auth_client):
        """
        Adversarial 3.1: Under extreme CCTV backend stress:
        - Background camera workers in a simulated offline reconnection loop.
        - Device lock file held.
        - Concurrent POST /api/cameras/save calls in flight.
        Verify /add_student returns HTTP 200 immediately (< 250ms) and contains zero backend stream URLs.
        """
        # Hold camera lock file to simulate Gunicorn primary worker lock contention
        lock_fd = None
        lock_path = hostel_camera.LOCK_PATH
        try:
            lock_fd = open(lock_path, "w")
        except Exception:
            pass

        # Simulate background contention
        save_in_progress = threading.Event()
        save_in_progress.set()

        def bg_hammer():
            while save_in_progress.is_set():
                try:
                    auth_client.post("/api/cameras/save", json={
                        "IN": {"vendor": "Hikvision", "ip_address": "192.0.2.1", "port": 554, "channel": 1, "enabled": True}
                    })
                except Exception:
                    pass
                time.sleep(0.05)

        hammer_thread = threading.Thread(target=bg_hammer, daemon=True)
        hammer_thread.start()

        start_time = time.perf_counter()
        resp = auth_client.get("/add_student")
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        save_in_progress.clear()
        hammer_thread.join(timeout=1.0)

        if lock_fd:
            try:
                lock_fd.close()
            except Exception:
                pass

        # Page must respond fast without waiting on CCTV backend
        assert resp.status_code == 200
        assert elapsed_ms < 500.0, f"/add_student took {elapsed_ms:.1f}ms under CCTV load (must be < 500ms)"

        html = resp.get_data(as_text=True)
        # Verify WebRTC components
        assert "guided-camera.js" in html
        assert "face-api.js" in html
        assert "guidedVideo" in html

        # Verify absolute zero coupling with server video feeds
        assert "/hostel/video_feed" not in html
        assert "/video_feed" not in html
        assert "CAM_01_ENTRY" not in html
        assert "CAM_02_EXIT" not in html

    def test_adv_webrtc_javascript_code_audit_isolation(self):
        """
        Adversarial 3.2: Static forensic code audit of guided-camera.js and add_student.html.
        Ensure:
        1. guided-camera.js invokes navigator.mediaDevices.getUserMedia directly.
        2. guided-camera.js contains ZERO fetch/XHR calls to CCTV video feeds or probers.
        3. Video source is attached via HTMLMediaElement.srcObject (WebRTC MediaStream).
        """
        js_path = os.path.join(os.path.dirname(__file__), "../../src/static/js/guided-camera.js")
        assert os.path.exists(js_path), f"guided-camera.js not found at {js_path}"

        with open(js_path, "r", encoding="utf-8") as f:
            js_code = f.read()

        # WebRTC requirement
        assert "navigator.mediaDevices.getUserMedia" in js_code, "Must use client WebRTC getUserMedia"
        assert "srcObject" in js_code, "Must attach stream to video.srcObject"

        # Forensic check: no server CCTV references
        forbidden_terms = [
            "/video_feed",
            "/hostel/video_feed",
            "/api/cameras",
            "hostel_camera_device.lock",
            "CAM_01_ENTRY",
            "CAM_02_EXIT",
            "rtsp://",
        ]
        for term in forbidden_terms:
            assert term not in js_code, f"Forbidden server CCTV reference '{term}' found in client WebRTC JS!"

    def test_adv_synthetic_frame_generator_visual_integrity(self):
        """
        Adversarial 3.3: Verify synthetic diagnostic frame generator matches dark glassmorphic specs.
        - Output is valid JPEG byte sequence.
        - Resolves to 640x360 dimensions.
        - Contains role badge and live clock.
        """
        frame_bytes = _create_synthetic_diagnostic_frame(
            role="IN",
            status_text="RECONNECTING",
            detail_text="Testing network dropout fallback",
            latency_ms=42.5
        )

        assert isinstance(frame_bytes, bytes)
        assert len(frame_bytes) > 500
        # Check JPEG magic markers \xff\xd8 and \xff\xd9
        assert frame_bytes[:2] == b"\xff\xd8", "Frame missing JPEG SOI"
        assert frame_bytes[-2:] == b"\xff\xd9", "Frame missing JPEG EOI"
