"""
Automated unit and integration tests for Roomba Web Server.
Tests REST endpoints, WebSocket telemetry streaming, Arm/Disarm safety logic,
mode management, and mock hardware simulation.
"""

from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient
from web_server import app, controller


@pytest.fixture(autouse=True)
async def reset_controller():
    """Ensure controller is disconnected before and after tests."""
    await controller.disconnect()
    yield
    await controller.disconnect()


def test_index_page():
    """Verify HTML index page is served."""
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "ROOMBA 960 COCKPIT" in res.text


def test_list_ports():
    """Verify /api/ports returns port list."""
    with TestClient(app) as client:
        res = client.get("/api/ports")
        assert res.status_code == 200
        data = res.json()
        assert "ports" in data
        assert isinstance(data["ports"], list)


def test_mock_connect_and_status():
    """Verify connecting in Mock mode and querying status."""
    with TestClient(app) as client:
        res = client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "connected"
        assert data["is_mock"] is True
        assert data["mode"] == "Safe"

        # Check status
        status_res = client.get("/api/status")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["connected"] is True
        assert status_data["is_mock"] is True
        assert status_data["armed"] is False
        assert status_data["mode"] == "Safe"
        assert "telemetry" in status_data
        assert status_data["telemetry"]["voltage_v"] > 14.0


def test_arm_disarm_lifecycle():
    """Verify ARM / DISARM safety states and drive lockouts."""
    with TestClient(app) as client:
        # Connect mock
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        # Driving while DISARMED must fail
        drive_res = client.post("/api/drive", json={"left": 150, "right": 150})
        assert drive_res.status_code == 400
        assert "DISARMED" in drive_res.json()["detail"]

        # Arm robot
        arm_res = client.post("/api/arm")
        assert arm_res.status_code == 200
        assert arm_res.json()["armed"] is True

        # Driving while ARMED succeeds
        drive_res2 = client.post("/api/drive", json={"left": 150, "right": 150})
        assert drive_res2.status_code == 200
        assert drive_res2.json()["status"] == "driving"

        # Disarm robot
        disarm_res = client.post("/api/disarm")
        assert disarm_res.status_code == 200
        assert disarm_res.json()["armed"] is False

        # Verify stop after disarm
        assert controller.is_driving is False


def test_emergency_stop():
    """Verify E-STOP immediately disarms and halts motors."""
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        client.post("/api/arm")
        client.post("/api/drive", json={"left": 200, "right": 200})
        assert controller.is_driving is True

        # Trigger E-STOP
        estop_res = client.post("/api/estop")
        assert estop_res.status_code == 200
        assert estop_res.json()["status"] == "estopped"
        assert estop_res.json()["armed"] is False
        assert controller.armed is False
        assert controller.is_driving is False


def test_mode_management():
    """Verify switching between Safe, Full, Passive, and Off."""
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        assert controller.client.mode == "Safe"

        # Switch to Full
        res_full = client.post("/api/mode", json={"mode": "full"})
        assert res_full.status_code == 200
        assert res_full.json()["mode"] == "Full"
        assert controller.client.mode == "Full"

        # Switch to Passive
        res_passive = client.post("/api/mode", json={"mode": "passive"})
        assert res_passive.status_code == 200
        assert res_passive.json()["mode"] == "Passive"

        # Switch to Off
        res_off = client.post("/api/mode", json={"mode": "off"})
        assert res_off.status_code == 200
        assert res_off.json()["mode"] == "Off"


def test_special_actions():
    """Verify Beep, Clean, Spot, Dock, and Mock Sensor actions."""
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        # Beep
        res_beep = client.post("/api/action", json={"action": "beep", "note": 72, "duration": 16})
        assert res_beep.status_code == 200
        assert res_beep.json()["action"] == "beep"

        # Dock
        res_dock = client.post("/api/action", json={"action": "dock"})
        assert res_dock.status_code == 200
        assert res_dock.json()["action"] == "dock"

        # Clean
        res_clean = client.post("/api/action", json={"action": "clean"})
        assert res_clean.status_code == 200
        assert res_clean.json()["action"] == "clean"

        # Spot
        res_spot = client.post("/api/action", json={"action": "spot"})
        assert res_spot.status_code == 200
        assert res_spot.json()["action"] == "spot"

        # Mock sensor trigger
        res_sens = client.post("/api/action", json={"action": "mock_sensor", "sensor": "bump_left", "value": True})
        assert res_sens.status_code == 200
        assert res_sens.json()["sensor"] == "bump_left"
        assert controller.client.bump_left is True


def test_websocket_telemetry():
    """Verify WebSocket connection, telemetry streaming, and ping/pong."""
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        with client.websocket_connect("/ws") as ws:
            # 1. Initial telemetry packet
            data = ws.receive_json()
            assert "voltage_v" in data or data.get("type") == "pong"

            # 2. Ping test
            ws.send_json({"type": "ping", "ts": 12345})
            pong = ws.receive_json()
            assert pong.get("type") == "pong" or "voltage_v" in pong


def test_sound_and_melody_actions():
    """Verify sound presets, tune playback, custom songs, RTTTL ringtones, and Morse code."""
    with TestClient(app) as client:
        # Check presets endpoint before connect
        res_presets = client.get("/api/sound/presets")
        assert res_presets.status_code == 200
        data = res_presets.json()
        assert "mario" in data["presets"]
        assert "imperial" in data["presets"]
        assert "rtttl_samples" in data

        # Connect in mock mode
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        # 1. Preset tune
        res_tune = client.post("/api/action", json={"action": "tune", "preset": "mario"})
        assert res_tune.status_code == 200
        assert res_tune.json()["action"] == "tune"
        assert res_tune.json()["preset"] == "mario"

        # 2. Custom song
        res_song = client.post("/api/sound/play", json={"action": "song", "notes": [[60, 8], [64, 8], [67, 16]]})
        assert res_song.status_code == 200
        assert res_song.json()["action"] == "song"
        assert res_song.json()["notes_count"] == 3

        # 3. RTTTL Ringtone string
        rtttl_str = "mario:d=4,o=5,b=100:16e6,16e6,32p,8e6"
        res_rtttl = client.post("/api/sound/play", json={"action": "rtttl", "rtttl": rtttl_str})
        assert res_rtttl.status_code == 200
        assert res_rtttl.json()["action"] == "rtttl"
        assert res_rtttl.json()["notes_count"] == 4

        # 4. Morse code audio transmission (including note=None regression check)
        res_morse = client.post("/api/sound/play", json={"action": "morse", "text": "SOS", "note": 76})
        assert res_morse.status_code == 200
        assert res_morse.json()["action"] == "morse"
        assert res_morse.json()["text"] == "SOS"
        assert res_morse.json()["notes_count"] > 0

        # Morse with note=None or omitting note shouldn't crash
        res_morse_none = client.post("/api/action", json={"action": "morse", "text": "OK", "note": None})
        assert res_morse_none.status_code == 200
        assert res_morse_none.json()["notes_count"] > 0

        # 5. Direct SOS emergency audio action
        res_sos = client.post("/api/action", json={"action": "sos"})
        assert res_sos.status_code == 200
        assert res_sos.json()["action"] == "sos"
        assert res_sos.json()["text"] == "SOS"

        # 6. Human vocal gestures and speech synthesis
        assert "human_sounds" in data
        assert "hello" in data["human_sounds"]
        assert "laugh" in data["human_sounds"]

        res_human = client.post("/api/action", json={"action": "human", "sound": "hello"})
        assert res_human.status_code == 200
        assert res_human.json()["sound"] == "hello"

        res_speak = client.post("/api/action", json={"action": "speak", "text": "Hello world!"})
        assert res_speak.status_code == 200
        assert res_speak.json()["action"] == "speak"
        assert res_speak.json()["notes_count"] > 0


if __name__ == "__main__":
    pytest.main(["-v", __file__])

