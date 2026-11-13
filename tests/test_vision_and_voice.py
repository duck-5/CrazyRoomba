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
    ]:
        assert elem_id in html
