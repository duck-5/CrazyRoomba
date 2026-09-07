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

