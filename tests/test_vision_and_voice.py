"""
Tests for Hardware Resilience (Robot/Camera/Audio Retry),
Camera Person Vision & Follow Mode Integration,
and English TTS / STT / Voice Command APIs.
"""

import io
import wave
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from roomba.web.app import create_app, controller


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _make_silent_wav_bytes(duration_s: float = 0.2, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * duration_s))
    return buf.getvalue()


def test_hardware_status_and_retry_without_hardware(client):
    """Server must not crash when robot, camera, mic, or speakers are absent."""
    res = client.get("/api/hardware/status")
    assert res.status_code == 200
    data = res.json()
    assert "robot" in data
    assert "camera" in data
    assert "voice" in data

    # Robot retry with no ports should return connected=False and an error message
    with patch("roomba.core.controller.find_roomba_port", return_value=None):
        r_res = client.post("/api/robot/retry")
        assert r_res.status_code == 200
        r_data = r_res.json()
        assert r_data["connected"] is False
        assert r_data["error"]

    # Camera retry when OpenCV camera fails to open should not crash
    with patch("roomba.perception.camera.OpenCVCameraSource.open", new_callable=AsyncMock, return_value=False):
        c_res = client.post("/api/camera/retry", json={"mock": False})
        assert c_res.status_code == 200
        c_data = c_res.json()
        assert c_data["available"] is False
        assert c_data["status"] == "error"
        assert c_data["error"]

    # Snapshot when camera unavailable returns 503 cleanly
    snap = client.get("/api/camera/snapshot")
    assert snap.status_code == 503


def test_unified_hardware_retry_endpoint(client):
    with patch("roomba.core.controller.find_roomba_port", return_value=None), \
         patch("roomba.perception.camera.OpenCVCameraSource.open", new_callable=AsyncMock, return_value=False):
        res = client.post("/api/hardware/retry")
        assert res.status_code == 200
        data = res.json()
        assert "robot" in data and "camera" in data and "voice" in data


def test_mock_camera_and_follow_person_mode(client):
    """Mock camera should detect simulated person and allow switching to follow_person mode."""
    # Connect mock robot first
    conn = client.post("/api/connect", json={"mock": True})
    assert conn.status_code == 200

    # Enable mock camera
    cam = client.post("/api/camera/mock")
    assert cam.status_code == 200
    cam_data = cam.json()
    assert cam_data["available"] is True
    assert cam_data["is_mock"] is True

    # Start follow_person via /api/modes/start (also verifies ModeScriptRequest fix)
    mode_res = client.post("/api/modes/start", json={"mode": "follow_person"})
    assert mode_res.status_code == 200
    assert mode_res.json()["active_mode"] == "follow_person"

    # Stop mode & camera cleanly
    client.post("/api/modes/stop")
    stop_cam = client.post("/api/camera/stop")
    assert stop_cam.status_code == 200
    client.post("/api/disconnect")


def test_voice_status_retry_and_tts(client):
    status_res = client.get("/api/voice/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["tts"]["language"] == "en"
    assert status_data["stt"]["language"] == "en-US"
    assert status_data["tts"]["browser_fallback_ready"] is True
    assert status_data["stt"]["browser_fallback_ready"] is True

    retry_res = client.post("/api/voice/retry")
    assert retry_res.status_code == 200

    tts_res = client.post("/api/voice/tts", json={"text": "Hello Roomba, systems online."})
    assert tts_res.status_code == 200
    tts_data = tts_res.json()
    assert tts_data["text"] == "Hello Roomba, systems online."
    assert "browser_fallback" in tts_data


def test_voice_commands_english(client):
    client.post("/api/connect", json={"mock": True})

    # Follow me -> switches to follow_person
    res = client.post("/api/voice/command", json={"text": "follow me", "execute": True, "speak_reply": False})
    assert res.status_code == 200
    data = res.json()
    assert data["recognized"] is True
    assert data["intent"] == "mode_follow"
    assert data["executed"] is True
    assert controller.mode_manager.active_name == "follow_person"

    # Wander -> switches to wander
    res = client.post("/api/voice/command", json={"text": "please wander around", "execute": True, "speak_reply": False})
    assert res.status_code == 200
    assert res.json()["intent"] == "mode_wander"
    assert controller.mode_manager.active_name == "wander"

    # Battery status
    res = client.post("/api/voice/command", json={"text": "what is your battery status", "execute": True, "speak_reply": False})
    assert res.status_code == 200
    assert res.json()["intent"] == "status"
    assert "battery" in res.json()["reply"].lower()

    # Stop
    res = client.post("/api/voice/command", json={"text": "stop", "execute": True, "speak_reply": False})
    assert res.status_code == 200
    assert res.json()["intent"] == "stop"

    # Unknown phrase
    res = client.post("/api/voice/command", json={"text": "purple banana spaceship", "execute": True, "speak_reply": False})
    assert res.status_code == 200
    assert res.json()["recognized"] is False

    client.post("/api/disconnect")


def test_voice_stt_upload_graceful_fallback(client):
    wav_bytes = _make_silent_wav_bytes()
    res = client.post(
        "/api/voice/stt",
        files={"audio": ("test.wav", wav_bytes, "audio/wav")},
        data={"execute": "false", "speak_reply": "false"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "stt" in data


def test_ui_contains_resilience_vision_and_voice_elements(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    for elem_id in [
        "hardware-alert-banner",
        "btn-retry-all-hw",
        "btn-retry-camera",
        "btn-mock-camera",
        "camera-stream-img",
        "btn-toggle-follow",
        "btn-retry-voice",
        "input-tts-text",
        "btn-speak-tts",
        "btn-browser-stt",
        "input-stt-command",
        "select-vision-target",
        "cat-detect-badge",
        "btn-toggle-pet-companion",
        "btn-ask-ai",
        "btn-scene-ai",
        "input-ai-prompt",
    ]:
        assert elem_id in html


def test_lifespan_starts_live_vision_and_mock_loops():
    """Verify configure_startup runs vision and controller loops inside FastAPI's live event loop."""
    import time
    from roomba.web.app import configure_startup, startup_options

    prev = dict(startup_options)
    try:
        configure_startup(mock=True, init_vision=True)
        app = create_app()
        with TestClient(app) as c:
            time.sleep(0.25)
            status = c.get("/api/hardware/status").json()
            assert status["robot"]["connected"] is True
            assert status["robot"]["is_mock"] is True
            assert status["camera"]["available"] is True
            assert status["camera"]["is_mock"] is True
            assert status["camera"]["frame_count"] >= 1
            assert status["camera"]["person_detected"] is True
            assert "target_person" in controller.latest_perception
    finally:
        startup_options.update(prev)


def test_hog_2d_weights_conversion():
    """Verify _process_real_frame_sync handles OpenCV (N, 1) 2D weights arrays safely."""
    import numpy as np
    from unittest.mock import MagicMock
    from roomba.perception.vision import VisionService

    vs = VisionService()
    fake_cv2 = MagicMock()
    fake_cv2.IMWRITE_JPEG_QUALITY = 1
    fake_cv2.FONT_HERSHEY_SIMPLEX = 0
    fake_cv2.ROTATE_180 = 1
    fake_cv2.rotate.side_effect = lambda f, code: f
    fake_cv2.resize.side_effect = lambda f, sz: np.zeros((sz[1], sz[0], 3), dtype=np.uint8)
    fake_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

    fake_hog = MagicMock()
    fake_hog.detectMultiScale.return_value = (
        np.array([[40, 20, 80, 160]]),
        np.array([[1.2]]),  # 2D (N, 1) array as returned by some OpenCV builds
    )
    vs._cv2 = fake_cv2
    vs._hog = fake_hog

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    target, jpeg = vs._process_real_frame_sync(frame)
    assert target is not None
    assert target["confidence"] > 0.35
    assert jpeg == b"\x01\x02\x03"


def test_camera_auto_scan_skips_pi_internal_nodes(monkeypatch):
    """OpenCVCameraSource should auto-scan /dev/video* and find USB camera on non-zero index."""
    import asyncio
    import sys
    import numpy as np
    from unittest.mock import MagicMock
    from roomba.perception import camera as cam_mod

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        cam_mod,
        "discover_video_devices",
        lambda: [
            {"index": 0, "path": "/dev/video0", "name": "rp1-cfe-csi2-ch0", "is_pi_internal": True},
            {"index": 1, "path": "/dev/video1", "name": "pispbe-output", "is_pi_internal": True},
            {"index": 8, "path": "/dev/video8", "name": "HD USB Camera: HD USB Camera", "is_pi_internal": False},
        ],
    )

    fake_cap_bad = MagicMock()
    fake_cap_bad.isOpened.return_value = False

    fake_cap_good = MagicMock()
    fake_cap_good.isOpened.return_value = True
    fake_cap_good.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))

    def fake_videocapture(target, *args, **kwargs):
        if target == "/dev/video8":
            return fake_cap_good
        return fake_cap_bad

    fake_cv2 = MagicMock()
    fake_cv2.CAP_V4L2 = 200
    fake_cv2.CAP_ANY = 0
    fake_cv2.CAP_PROP_FOURCC = 6
    fake_cv2.CAP_PROP_FRAME_WIDTH = 3
    fake_cv2.CAP_PROP_FRAME_HEIGHT = 4
    fake_cv2.VideoWriter_fourcc.return_value = 1196444237
    fake_cv2.VideoCapture.side_effect = fake_videocapture

    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    src = cam_mod.OpenCVCameraSource(device_index=0, auto_scan=True)
    ok = asyncio.run(src.open())
    assert ok is True
    assert src.device_index == 8
    assert src.device_path == "/dev/video8"
    assert src.backend_name == "opencv-v4l2"
    asyncio.run(src.close())


def test_mobilenet_ssd_person_detection():
    """Verify _process_real_frame_sync detects class 15 (person) from MobileNet-SSD DNN output."""
    import numpy as np
    from unittest.mock import MagicMock
    from roomba.perception.vision import VisionService

    vs = VisionService()
    fake_cv2 = MagicMock()
    fake_cv2.IMWRITE_JPEG_QUALITY = 1
    fake_cv2.FONT_HERSHEY_SIMPLEX = 0
    fake_cv2.ROTATE_180 = 1
    fake_cv2.rotate.side_effect = lambda f, code: f
    fake_cv2.resize.side_effect = lambda f, sz: np.zeros((sz[1], sz[0], 3), dtype=np.uint8)
    fake_cv2.dnn.blobFromImage.return_value = np.zeros((1, 3, 300, 300), dtype=np.float32)
    fake_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

    fake_net = MagicMock()
    # Shape (1, 1, 1, 7): [batch, id, class_id=15, conf=0.88, x1, y1, x2, y2] -> 7 elements
    det = np.array([[[[0.0, 15.0, 0.88, 0.2, 0.1, 0.6, 0.9]]]], dtype=np.float32)
    fake_net.forward.return_value = det

    vs._cv2 = fake_cv2
    vs._ssd_net = fake_net
    vs.detector_backend = "mobilenet-ssd"

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target, jpeg = vs._process_real_frame_sync(frame)
    assert target is not None
    assert target["confidence"] == 0.88
    assert 0.39 <= target["x_center"] <= 0.41
    assert 0.39 <= target["bbox_width"] <= 0.41
    assert jpeg == b"\x01\x02\x03"


def test_yolox_coco_person_detection():
    """Verify _process_real_frame_sync decodes YOLOX (1, 8400, 85) COCO person output."""
    import numpy as np
    from unittest.mock import MagicMock
    from roomba.perception.vision import VisionService

    vs = VisionService()
    vs._init_yolox_anchors()

    fake_cv2 = MagicMock()
    fake_cv2.IMWRITE_JPEG_QUALITY = 1
    fake_cv2.FONT_HERSHEY_SIMPLEX = 0
    fake_cv2.INTER_LINEAR = 1
    fake_cv2.ROTATE_180 = 1
    fake_cv2.rotate.side_effect = lambda f, code: f
    fake_cv2.resize.side_effect = lambda f, sz, **kw: np.zeros((sz[1], sz[0], 3), dtype=np.uint8)
    fake_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

    # Build synthetic (1, 8400, 85) YOLOX output with a person at anchor 0
    # At anchor 0: grid=(0, 0), stride=8 -> cx=40*8=320, cy=30*8=240
    # exp(3.401)*8 ~= 240, exp(3.689)*8 ~= 320
    outs = np.zeros((1, 8400, 85), dtype=np.float32)
    outs[0, 0, 0] = 40.0
    outs[0, 0, 1] = 30.0
    outs[0, 0, 2] = np.log(240.0 / 8.0)
    outs[0, 0, 3] = np.log(320.0 / 8.0)
    outs[0, 0, 4] = 0.90  # objectness
    outs[0, 0, 5] = 0.90  # COCO class 0 (person) -> score = 0.81

    fake_net = MagicMock()
    fake_net.getUnconnectedOutLayersNames.return_value = ["output"]
    fake_net.forward.return_value = [outs]

    vs._cv2 = fake_cv2
    vs._yolox_net = fake_net
    vs.detector_backend = "yolox-coco"

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target, jpeg = vs._process_real_frame_sync(frame)
    assert target is not None
    assert abs(target["confidence"] - 0.81) < 0.02
    assert abs(vs.last_raw_confidence - 0.81) < 0.02
    assert 0.45 <= target["x_center"] <= 0.55
    assert jpeg == b"\x01\x02\x03"
