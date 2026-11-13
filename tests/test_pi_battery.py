"""
Tests for Raspberry Pi battery monitoring and its Web API / UI integration.
"""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from roomba.core.pi_battery import PiBatteryMonitor, _estimate_liion_percent
from roomba.web.app import app, controller


def test_estimate_liion_percent():
    assert _estimate_liion_percent(4.2) == 100.0
    assert _estimate_liion_percent(3.0) == 0.0
    assert _estimate_liion_percent(8.4) == 100.0
    assert _estimate_liion_percent(7.2) == 50.0


def test_pi_battery_mock_mode():
    monitor = PiBatteryMonitor(cache_ttl_s=0.0)
    status = monitor.get_status(is_mock=True)
    assert status["available"] is True
    assert status["source"] == "mock"
    assert 0.0 <= status["percent"] <= 100.0
    assert status["voltage_v"] > 0.0
    assert status["under_voltage"] is False


def test_pi_battery_sysfs_reading(tmp_path: Path):
    bat_dir = tmp_path / "pijuice"
    bat_dir.mkdir()
    (bat_dir / "type").write_text("Battery\n")
    (bat_dir / "capacity").write_text("76\n")
    (bat_dir / "voltage_now").write_text("4050000\n")
    (bat_dir / "current_now").write_text("520000\n")
    (bat_dir / "status").write_text("Discharging\n")

    monitor = PiBatteryMonitor(cache_ttl_s=0.0, sysfs_root=tmp_path)
    status = monitor.get_status(is_mock=False)
    assert status["available"] is True
    assert status["percent"] == 76.0
    assert status["voltage_v"] == 4.05
    assert status["current_ma"] == -520
    assert status["charging"] is False
    assert status["status"] == "Discharging"
    assert status["source"] == "sysfs:pijuice"


def test_pi_battery_web_endpoints_and_ui():
    with TestClient(app) as client:
        # HTML contains Pi battery UI elements
        index_res = client.get("/")
        assert index_res.status_code == 200
        assert "pi-battery-fill" in index_res.text
        assert "pi-battery-pct-text" in index_res.text
        assert "quick-pi-battery-text" in index_res.text

        # Hardware status includes pi_battery
        hw_res = client.get("/api/hardware/status")
        assert hw_res.status_code == 200
        assert "pi_battery" in hw_res.json()

        # Connect in mock mode and verify /api/pi/battery & /api/status
        client.post("/api/connect", json={"mock": True, "mode": "Safe"})
        pi_res = client.get("/api/pi/battery")
        assert pi_res.status_code == 200
        pi_data = pi_res.json()
        assert pi_data["available"] is True
        assert pi_data["source"] == "mock"
        assert pi_data["percent"] > 0

        status_res = client.get("/api/status")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["pi_battery"]["source"] == "mock"
        assert status_data["telemetry"]["pi_battery"]["source"] == "mock"
