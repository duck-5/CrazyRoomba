"""
Raspberry Pi Battery & Power Monitor.

Supports multiple power/battery telemetry sources with graceful fallback:
1. Mock simulation (when Roomba is in Mock Sim mode)
2. Linux sysfs power_supply (/sys/class/power_supply/*) — PiJuice, PiSugar, standard UPS/battery drivers
3. INA219 I2C UPS HAT (Waveshare UPS HAT, Geekworm, Adafruit) via smbus2/smbus
4. psutil.sensors_battery() fallback
5. Raspberry Pi PMIC / vcgencmd (get_throttled, measure_temp, pmic_read_adc)
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from roomba.config import is_raspberry_pi

logger = logging.getLogger(__name__)

# INA219 I2C registers & common Raspberry Pi UPS HAT addresses
_INA219_CANDIDATE_ADDRS = (0x41, 0x42, 0x43, 0x40)
_INA219_REG_SHUNT_V = 0x01
_INA219_REG_BUS_V = 0x02


def _estimate_liion_percent(voltage_v: float) -> float:
    """Estimate Li-ion/LiPo state-of-charge % from pack voltage (auto-detects 1S / 2S / 3S)."""
    if voltage_v <= 0:
        return 0.0
    if voltage_v < 4.6:
        cells = 1
    elif voltage_v < 9.2:
        cells = 2
    else:
        cells = 3

    v_cell = voltage_v / cells
    # Linearized Li-ion discharge curve (3.0V = 0%, 4.2V = 100%)
    pct = (v_cell - 3.0) / (4.2 - 3.0) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)


class PiBatteryMonitor:
    """Reads Raspberry Pi battery / UPS / PMIC power telemetry with caching."""

    def __init__(self, cache_ttl_s: float = 2.0, sysfs_root: Path = Path("/sys/class/power_supply")):
        self._cache_ttl_s = cache_ttl_s
        self._sysfs_root = sysfs_root
        self._last_read_ts: float = 0.0
        self._last_is_mock: Optional[bool] = None
        self._cached_status: Optional[Dict[str, Any]] = None

        # Mock state
        self._mock_start_ts: float = time.monotonic()
        self._mock_initial_pct: float = 88.0

    def get_status(self, is_mock: bool = False, force: bool = False) -> Dict[str, Any]:
        """Return current Raspberry Pi battery/power status dictionary."""
        now = time.monotonic()
        if (
            not force
            and self._cached_status is not None
            and self._last_is_mock == is_mock
            and (now - self._last_read_ts) < self._cache_ttl_s
        ):
            return dict(self._cached_status)

        status = self._read_mock() if is_mock else self._read_hardware()
        self._cached_status = status
        self._last_read_ts = now
        self._last_is_mock = is_mock
        return dict(status)

    def _read_mock(self) -> Dict[str, Any]:
        """Simulate a realistic Raspberry Pi UPS battery in Mock Sim mode."""
        elapsed = time.monotonic() - self._mock_start_ts
        # Gentle drain ~0.01% per second, wrapping cleanly above 25%
        pct = round(max(25.0, self._mock_initial_pct - (elapsed * 0.01) % 60.0), 1)
        # 2S Li-ion pack (6.0V - 8.4V) regulated to Pi 5V
        voltage_v = round(6.8 + (pct / 100.0) * 1.6, 2)
        return {
            "available": True,
            "percent": pct,
            "voltage_v": voltage_v,
            "current_ma": -680,
            "charging": False,
            "status": "Discharging",
            "under_voltage": False,
            "temperature_c": 45.2,
            "source": "mock",
        }

    def _read_hardware(self) -> Dict[str, Any]:
        """Probe Linux sysfs, I2C INA219, psutil, and Raspberry Pi vcgencmd."""
        result: Dict[str, Any] = {
            "available": False,
            "percent": None,
            "voltage_v": None,
            "current_ma": None,
            "charging": False,
            "status": "Unavailable",
            "under_voltage": False,
            "temperature_c": None,
            "source": "unavailable",
        }

        # 1. Try Linux /sys/class/power_supply/*
        sysfs_data = self._read_sysfs()
        if sysfs_data:
            result.update(sysfs_data)

        # 2. Try INA219 I2C UPS HAT if sysfs had no battery
        if not result["available"]:
            ina_data = self._read_ina219()
            if ina_data:
                result.update(ina_data)

        # 3. Try psutil.sensors_battery() fallback
        if not result["available"]:
            psutil_data = self._read_psutil()
            if psutil_data:
                result.update(psutil_data)

        # 4. Enrich with Raspberry Pi vcgencmd (undervoltage, temp, Pi 5 PMIC 5V rail)
        if is_raspberry_pi():
            self._enrich_vcgencmd(result)

        return result

    def _read_sysfs(self) -> Optional[Dict[str, Any]]:
        """Read battery telemetry from /sys/class/power_supply/*."""
        if not self._sysfs_root.exists():
            return None

        try:
            entries = sorted(self._sysfs_root.iterdir())
        except OSError:
            return None

        for supply in entries:
            if not supply.is_dir():
                continue
            supply_type = self._read_text(supply / "type") or ""
            name_lower = supply.name.lower()
            is_battery = supply_type.lower() in ("battery", "ups") or any(
                k in name_lower for k in ("bat", "ups", "pijuice", "pisugar")
            )
            if not is_battery:
                continue

            cap_str = self._read_text(supply / "capacity")
            volt_str = self._read_text(supply / "voltage_now")
            curr_str = self._read_text(supply / "current_now")
            stat_str = self._read_text(supply / "status")

            if cap_str is None and volt_str is None:
                continue

            voltage_v: Optional[float] = None
            if volt_str is not None:
                try:
                    voltage_v = round(int(volt_str) / 1_000_000.0, 2)
                except ValueError:
                    pass

            percent: Optional[float] = None
            if cap_str is not None:
                try:
                    percent = round(max(0.0, min(100.0, float(cap_str))), 1)
                except ValueError:
                    pass
            elif voltage_v is not None:
                percent = _estimate_liion_percent(voltage_v)

            current_ma: Optional[int] = None
            if curr_str is not None:
                try:
                    current_ma = int(int(curr_str) / 1000)
                except ValueError:
                    pass

            status_text = stat_str or "Unknown"
            charging = status_text.lower() == "charging"
            if status_text.lower() == "discharging" and current_ma is not None and current_ma > 0:
                current_ma = -current_ma

            return {
                "available": True,
                "percent": percent,
                "voltage_v": voltage_v,
                "current_ma": current_ma,
                "charging": charging,
                "status": status_text,
                "source": f"sysfs:{supply.name}",
            }

        return None

    def _read_ina219(self) -> Optional[Dict[str, Any]]:
        """Read bus voltage & current from an INA219 I2C UPS HAT if present on /dev/i2c-1."""
        i2c_dev = Path("/dev/i2c-1")
        if not i2c_dev.exists():
            return None

        smbus_mod = None
        try:
            import smbus2 as smbus_mod  # type: ignore
        except ImportError:
            try:
                import smbus as smbus_mod  # type: ignore
            except ImportError:
                return None

        env_addr = os.getenv("ROOMBA_PI_BATTERY_I2C_ADDR")
        if env_addr:
            try:
                addrs = (int(env_addr, 0),)
            except ValueError:
                addrs = _INA219_CANDIDATE_ADDRS
        else:
            addrs = _INA219_CANDIDATE_ADDRS

        bus = None
        try:
            bus = smbus_mod.SMBus(1)
            for addr in addrs:
                try:
                    raw_bus = bus.read_word_data(addr, _INA219_REG_BUS_V)
                    # INA219 is big-endian; smbus read_word_data returns little-endian
                    swapped = ((raw_bus & 0xFF) << 8) | ((raw_bus >> 8) & 0xFF)
                    bus_mv = (swapped >> 3) * 4
                    voltage_v = round(bus_mv / 1000.0, 2)
                    if not (2.5 <= voltage_v <= 15.0):
                        continue

                    # Shunt voltage across standard 0.1 ohm resistor (LSB = 10 uV -> 0.1 mA)
                    current_ma: Optional[int] = None
                    try:
                        raw_shunt = bus.read_word_data(addr, _INA219_REG_SHUNT_V)
                        shunt_swapped = ((raw_shunt & 0xFF) << 8) | ((raw_shunt >> 8) & 0xFF)
                        if shunt_swapped & 0x8000:
                            shunt_swapped -= 0x10000
                        # Assuming standard 0.1 ohm shunt: I(mA) = (shunt * 10uV) / 0.1ohm = shunt * 0.1
                        current_ma = int(shunt_swapped * 0.1)
                    except OSError:
                        pass

                    charging = current_ma is not None and current_ma > 50
                    status_text = "Charging" if charging else "Discharging"
                    return {
                        "available": True,
                        "percent": _estimate_liion_percent(voltage_v),
                        "voltage_v": voltage_v,
                        "current_ma": current_ma,
                        "charging": charging,
                        "status": status_text,
                        "source": f"ina219:0x{addr:02x}",
                    }
                except OSError:
                    continue
        except OSError:
            return None
        finally:
            if bus is not None:
                try:
                    bus.close()
                except Exception:
                    pass

        return None

    def _read_psutil(self) -> Optional[Dict[str, Any]]:
        """Fallback to psutil.sensors_battery() if installed."""
        try:
            import psutil  # type: ignore
        except ImportError:
            return None

        try:
            batt = psutil.sensors_battery()
        except Exception:
            return None

        if batt is None:
            return None

        pct = round(max(0.0, min(100.0, float(batt.percent))), 1)
        charging = bool(batt.power_plugged)
        status_text = "Charging" if charging else "Discharging"
        if charging and pct >= 99.5:
            status_text = "Full"

        return {
            "available": True,
            "percent": pct,
            "voltage_v": None,
            "current_ma": None,
            "charging": charging,
            "status": status_text,
            "source": "psutil",
        }

    def _enrich_vcgencmd(self, result: Dict[str, Any]) -> None:
        """Read Raspberry Pi throttling flags, SoC temp, and Pi 5 PMIC 5V rail."""
        throttled_out = self._run_vcgencmd("get_throttled")
        if throttled_out:
            m = re.search(r"0x([0-9a-fA-F]+)", throttled_out)
            if m:
                flags = int(m.group(1), 16)
                result["under_voltage"] = bool(flags & 0x1)

        temp_out = self._run_vcgencmd("measure_temp")
        if temp_out:
            m = re.search(r"temp=([0-9.]+)", temp_out)
            if m:
                result["temperature_c"] = round(float(m.group(1)), 1)

        if result["voltage_v"] is None:
            pmic_out = self._run_vcgencmd("pmic_read_adc")
            if pmic_out:
                m = re.search(r"EXT5V_V\s+volt\(\d+\)=([0-9.]+)V", pmic_out)
                if m:
                    result["voltage_v"] = round(float(m.group(1)), 2)
                    if result["source"] == "unavailable":
                        result["source"] = "pmic"
                        result["status"] = "External 5V"

    @staticmethod
    def _run_vcgencmd(arg: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["vcgencmd", arg],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _read_text(path: Path) -> Optional[str]:
        try:
            if path.exists():
                return path.read_text().strip()
        except OSError:
            pass
        return None
