# Roomba 960 Modular Controller & Web Hub

A clean, production-ready Python controller, autonomous operating mode engine, and real-time Web Cockpit for the **iRobot Roomba 960** via its motherboard micro-USB port using the iRobot Open Interface (OI) protocol.

Designed to run as a primary robot controller on an onboard **Raspberry Pi** (Linux) mounted on the Roomba, while providing first-class support for **Windows** workstations during development and offline testing.

---

## 1. Project Layout

The repository is organized following professional Python robotics conventions:

```
.
├── deploy/                      # Production deployment tooling
│   ├── Dockerfile               # Multi-arch container (Raspberry Pi ARM64/ARMv7 & x86)
│   ├── docker-compose.yml       # Docker compose with serial & camera passthrough
│   └── roomba.service           # Linux systemd unit for auto-start on Pi boot
├── roomba/                      # Self-contained Python package
│   ├── __init__.py
│   ├── __main__.py              # Unified CLI entry point (`python -m roomba ...`)
│   ├── config.py                # Cross-platform config & Raspberry Pi board detection
│   ├── core/                    # Robot brain & central coordinator
│   │   ├── controller.py        # ARM/DISARM, watchdog, E-STOP & mode arbitrator
│   │   └── state.py             # DriveCommand and RobotState models
│   ├── driver/                  # Hardware interfacing & OI protocol
│   │   ├── client.py            # Async serial Roomba client (pyserial-asyncio)
│   │   ├── discovery.py         # Hardware VID:PID discovery across Windows & Linux
│   │   ├── mock.py              # Offline simulator for sensors, odometry & battery
│   │   ├── protocol.py          # OI v2 opcodes, 80-byte Packet 100 parser
│   │   └── sound.py             # Melodies, RTTTL ringtones & Morse code audio
│   ├── modes/                   # Autonomous Operating Modes & Scripts
│   │   ├── base.py              # BaseMode interface and RobotContext
│   │   ├── manager.py           # ModeManager & 10Hz autonomous control loop
│   │   ├── manual.py            # Manual teleoperation mode (WASD, D-pad, API)
│   │   ├── wander.py            # Obstacle avoidance wander (bumpers & cliffs)
│   │   └── follow_person.py     # Vision-guided person tracking stub (proportional steering)
│   ├── behaviors/               # Backward-compatible alias module for roomba.modes
│   ├── perception/              # Vision & sensor pipelines
│   │   └── camera.py            # Camera sources (Pi Camera / USB / Mock) & target injection
│   └── web/                     # Web server & dashboard
│       ├── app.py               # FastAPI REST API & WebSocket streaming
│       └── static/              # Packaged HTML5/CSS3/JS Cockpit UI assets
├── scripts/                     # Standalone CLI utilities
│   ├── run_server.py            # Web cockpit server launcher
│   ├── teleop.py                # Interactive terminal WASD teleop
│   ├── monitor.py               # Live hardware sensor monitor & snapshot tool
│   ├── verify.py                # Hardware connection and telemetry diagnostics
│   └── test_wheel.py            # Gentle drive wheel diagnostic test
├── tests/                       # Automated test suite (26 unit & integration tests)
├── pyproject.toml               # Package metadata, package data & console scripts
└── requirements.txt             # Python dependencies
```

---

## 2. Hardware & Connection Overview

- **Port:** Motherboard micro-USB port (located beneath top cover/dust bin).
- **USB Device:** Enumerates as a USB CDC ACM serial device:
  - **Vendor ID (VID):** `0x27A6` (iRobot Corporation)
  - **Product ID (PID):** `0x0002`
- **Default Port Paths:**
  - **Linux / Raspberry Pi:** `/dev/ttyACM0` or `/dev/ttyUSB0` (or symlink `/dev/serial/by-id/usb-iRobot...`)
  - **Windows:** `COM*` (e.g. `COM11`)
- **Baud Rate:** `115200` baud, 8 data bits, 1 stop bit, no parity.
- **Protocol:** iRobot Roomba Open Interface (OI) v2.

---

## 3. Installation & Setup

### A. Windows Workstation
```powershell
# Clone repository and install dependencies
git clone https://github.com/your-username/roomba-controller.git
cd roomba-controller
pip install -r requirements.txt
```

### B. Raspberry Pi (Bare-Metal Linux)
On Raspberry Pi OS (Debian bookworm/bullseye), grant your user serial and camera access:
```bash
# Add current user to dialout and video groups
sudo usermod -a -G dialout,video $USER

# Install Python requirements
pip install -r requirements.txt
```
*(Log out and back in once for group permissions to take effect).*

---

## 4. Unified CLI (`python -m roomba`)

The controller provides a single, unified entry point for all operations:

```bash
# 1. Launch Web Control Cockpit (default):
python -m roomba
# Options: python -m roomba web --port 8000 --mock --mode safe

# 2. Drive interactively with keyboard WASD:
python -m roomba teleop --speed 150

# 3. Inspect live hardware sensors:
python -m roomba monitor --rate 5
# Or print a single snapshot and exit:
python -m roomba monitor --once

# 4. Verify hardware connection & diagnostics:
python -m roomba verify

# 5. Gently test drive wheel movement:
python -m roomba test-wheel --speed 100 --duration 1.0 --mode full
```

*(You can also run any script directly from `scripts/`, e.g. `python scripts/run_server.py`).*

---

## 5. Web Control Cockpit Features

Open **[http://localhost:8000](http://localhost:8000)** (or `http://<pi-ip>:8000` over your local network).

1. **Live Sensor Telemetry:**
   - Real-time Left/Right Bumper indicators (glow red when pressed).
   - Real-time Wheel Drop indicators (glow amber when lifted).
   - 4 Floor Cliff sensors with reflection levels.
   - 6-zone Light Bumper IR proximity array across the front bumper.
   - Battery meter with dynamic gradient, voltage (V/mV), current (mA), and temperature.
   - Wheel encoders, distance, and angle odometry.
2. **Autonomous Operating Modes:**
   - Switch between **Manual Mode**, **Wander Mode (Obstacle Avoidance)**, and **Person Follower (Vision)** directly from the UI.
   - Real-time status and active mode indicators.
3. **Safety & Arming Interlock:**
   - **ARM / DISARM:** Movement controls are locked out while DISARMED.
   - **E-STOP:** Spacebar or UI button immediately halts wheel motors and disarms the robot.
   - **Dead-Man Switch:** Motors stop within 500ms if control pulses cease.
4. **Teleoperation:**
   - WASD Keyboard controls (`W`=Forward, `S`=Back, `A`=Left, `D`=Right, `Space`=E-Stop).
   - Touch/Mouse Virtual D-Pad.
   - Speed presets (100, 150, 250, 400 mm/s) and discrete nudge buttons.
5. **Sound & Music Synthesizer:**
   - Plays preset melodies (Mario, Imperial March, Zelda, Charge), custom RTTTL ringtones, and Morse code audio beeps.

---

## 6. Autonomous Operating Modes & Vision Pipeline

### Adding a Custom Operating Mode Script
Autonomous behaviors run inside an isolated control loop managed by `ModeManager`. To implement a new mode:

1. Create a class inheriting from `roomba.modes.base.BaseMode`:
```python
from roomba.modes.base import BaseMode, RobotContext
from roomba.core.state import DriveCommand

class LineFollowMode(BaseMode):
    name = "line_follower"
    description = "Follows floor line markers using cliff sensors"

    async def update(self, ctx: RobotContext) -> DriveCommand:
        # ctx.telemetry has live Roomba sensor data
        return DriveCommand.forward(150)
```

2. Register your mode in [`roomba/core/controller.py`](roomba/core/controller.py):
```python
self.mode_manager.register(LineFollowMode())
```

3. Activate it via the Web Cockpit UI or REST API:
```bash
curl -X POST http://localhost:8000/api/modes/start -H "Content-Type: application/json" -d '{"mode":"line_follower"}'
```

### Vision & Person Following Pipeline
- **`roomba.perception.camera.BaseCameraSource`**: Abstract camera interface supporting Picamera2, USB OpenCV, or Mock frame generation.
- **REST Target Injection (`POST /api/perception`)**: Feed bounding boxes from external object detection models (YOLO, MediaPipe, MobileNet):
  ```json
  {
    "target": {
      "target_person": {
        "x_center": 0.65,
        "bbox_width": 0.28,
        "confidence": 0.92
      }
    }
  }
  ```
- **Proportional Controller**: [`FollowPersonMode`](roomba/modes/follow_person.py) calculates lateral offset and steers the differential drive motors proportionally to center and follow the target.

---

## 7. Deployment on Raspberry Pi

### Option A: Systemd Auto-Start Daemon
To start the Roomba controller automatically on Raspberry Pi boot:

1. Edit [`deploy/roomba.service`](deploy/roomba.service) to match your Pi username and directory path (default: `/home/pi/roomba-controller`).
2. Install and enable the service:
   ```bash
   sudo cp deploy/roomba.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now roomba.service
   ```
3. Check status:
   ```bash
   sudo systemctl status roomba.service
   ```

### Option B: Docker Container
1. Build and launch:
   ```bash
   docker compose -f deploy/docker-compose.yml up -d --build
   ```
2. Inspect logs:
   ```bash
   docker compose -f deploy/docker-compose.yml logs -f
   ```

---

## 8. Automated Testing

Run the full test suite (26 unit and integration tests):

```powershell
pytest -v
```

---

## 9. License

Released under the MIT License.
