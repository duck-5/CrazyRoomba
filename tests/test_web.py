"""
Integration tests for Roomba Web Server, REST APIs, and WebSockets.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from roomba.web.app import app, controller


@pytest.fixture(autouse=True)
async def reset_controller():
    await controller.disconnect()
    yield
    await controller.disconnect()


def test_index_page():
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "ROOMBA 960 COCKPIT" in res.text


def test_list_ports():
    with TestClient(app) as client:
        res = client.get("/api/ports")
        assert res.status_code == 200
        data = res.json()
        assert "ports" in data
        assert isinstance(data["ports"], list)


def test_mock_connect_and_status():
    with TestClient(app) as client:
        res = client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "connected"
        assert data["is_mock"] is True

        status_res = client.get("/api/status")
        assert status_res.status_code == 200
        sdata = status_res.json()
        assert sdata["connected"] is True
        assert sdata["is_mock"] is True
        assert sdata["active_behavior"] == "manual"


def test_behavior_endpoints():
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        # List behaviors
        b_res = client.get("/api/behaviors")
        assert b_res.status_code == 200
        b_data = b_res.json()
        assert "behaviors" in b_data
        assert b_data["active"] == "manual"

        # Start Wander behavior
        start_res = client.post("/api/behaviors/start", json={"behavior": "wander"})
        assert start_res.status_code == 200
        assert start_res.json()["active_behavior"] == "wander"
        assert controller.behavior_manager.active_name == "wander"

        # Inject Perception
        perc_res = client.post("/api/perception", json={"target": {"target_person": {"x_center": 0.6}}})
        assert perc_res.status_code == 200

        # Stop behavior (back to manual)
        stop_res = client.post("/api/behaviors/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["active_behavior"] == "manual"


def test_arm_disarm_and_drive():
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        # Driving while disarmed fails
        d1 = client.post("/api/drive", json={"left": 100, "right": 100})
        assert d1.status_code == 400

        # Arm
        arm_res = client.post("/api/arm")
        assert arm_res.status_code == 200
        assert arm_res.json()["armed"] is True

        # Driving while armed succeeds
        d2 = client.post("/api/drive", json={"left": 100, "right": 100})
        assert d2.status_code == 200
        assert d2.json()["status"] == "driving"

        # E-STOP
        estop_res = client.post("/api/estop")
        assert estop_res.status_code == 200
        assert estop_res.json()["armed"] is False
        assert controller.armed is False


def test_websocket_telemetry():
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})

        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert "voltage_v" in data or data.get("type") == "pong"

            ws.send_json({"type": "ping", "ts": 9999})
            pong = ws.receive_json()
            assert pong.get("type") == "pong" or "voltage_v" in pong


def test_odometry_reset_endpoint():
    """Verify /api/odometry/reset resets odometry values."""
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        # Set mock encoder values
        client.post("/api/action", json={"action": "mock_sensor", "sensor": "distance_mm", "value": 500})

        # Trigger reset
        res = client.post("/api/odometry/reset")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        assert res.json()["action"] == "reset_odometry"


def test_mobile_elements_present():
    """Verify that mobile viewport, navigation tabs, and virtual joystick controllers are in the index page."""
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.text

        # Mobile viewport & web app tags
        assert 'name="viewport"' in html
        assert "viewport-fit=cover" in html
        assert "user-scalable=no" in html

        # Mobile Cockpit Tab Bar
        assert 'id="mobile-tab-bar"' in html
        assert 'data-tab="drive"' in html
        assert 'data-tab="schematic"' in html
        assert 'data-tab="power"' in html
        assert 'data-tab="console"' in html

        # Mobile Quick Status HUD
        assert 'id="mobile-quick-status"' in html
        assert 'id="btn-quick-arm"' in html

        # Large Virtual Analog Joystick Controller
        assert 'id="joystick-view"' in html
        assert 'id="joystick-base"' in html
        assert 'id="joystick-knob"' in html
        assert 'id="joystick-readout"' in html
        assert 'id="joystick-speed-readout"' in html

        # Controller Mode Switcher
        assert "controller-mode-switcher" in html
        assert 'id="tab-ctrl-joystick"' in html
        assert 'id="tab-ctrl-dpad"' in html


def test_smooth_differential_drive():
    """Verify that fine-grained differential drive speeds (as produced by analog joystick) are accepted."""
    with TestClient(app) as client:
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        client.post("/api/arm")

        # Smooth analog arc turn (left wheel faster, right wheel slower)
        res = client.post("/api/drive", json={"left": 210, "right": 140})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "driving"
        assert data["left"] == 210
        assert data["right"] == 140


def test_eight_bit_jukebox_and_soundmarks_html():
    """Verify 8-bit chiptune jukebox & sound marks are present in HTML, and old speech/mic grinder is absent."""
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.text

        # 8-Bit Chiptune Jukebox UI
        assert 'id="select-preset-tune"' in html
        assert 'value="tetris"' in html
        assert 'value="mario_kart_circuit"' in html
        assert 'value="mario_kart_start"' in html
        assert 'value="mario_overworld"' in html
        assert 'value="pacman"' in html
        assert 'value="zelda_theme"' in html
        assert 'value="doom_e1m1"' in html
        assert 'id="btn-play-tune"' in html

        # Robot Sound Marks Soundboard
        assert 'id="soundmarks-container"' in html
        assert 'data-mark="startup"' in html
        assert 'data-mark="dock_success"' in html
        assert 'data-mark="clean_done"' in html
        assert 'data-mark="ack"' in html
        assert 'data-mark="obstacle_alert"' in html
        assert 'data-mark="cliff_warning"' in html
        assert 'data-mark="low_battery"' in html

        # Verification that pseudo-speech / mic grinder elements have been completely removed
        assert 'id="btn-speak-voice"' not in html
        assert 'id="btn-record-mic"' not in html
        assert 'id="btn-grind-file"' not in html
        assert 'id="input-speech-text"' not in html



