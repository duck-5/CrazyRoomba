# Roomba 960 Modular Controller & Web Hub

A modular, cross-platform Python controller, autonomous behavior engine, and real-time Web Cockpit for the **iRobot Roomba 960** via its motherboard micro-USB port using the iRobot Open Interface (OI) protocol.

Designed to run as a primary robot controller on a **Raspberry Pi** (Linux) mounted on the Roomba, while maintaining full support for **Windows** workstations during development and testing.

---

## 1. Architecture Overview

The codebase is organized into a modular package under `roomba/` with clear separation of concerns:

```
├── roomba/                      # Core Controller Python Package
│   ├── config.py                # Cross-platform config & Raspberry Pi board detection
│   ├── driver/                  # Hardware & OI Protocol Layer
│   │   ├── protocol.py          # OI v2 opcodes, 80-byte Packet 100 parser, telemetry schema
│   │   ├── discovery.py         # Hardware VID:PID discovery across Windows & Linux
│   │   ├── client.py            # Async Roomba serial client (pyserial-asyncio)
│   │   ├── mock.py              # Offline simulator for sensors, odometry & battery
│   │   └── sound.py             # RTTTL ringtones, MIDI tunes & Morse code audio
│   ├── core/                    # Robot State & Coordination
│   │   ├── state.py             # DriveCommand and RobotState models
│   │   └── controller.py        # Central coordinator, ARM/DISARM, E-STOP & watchdog
│   ├── behaviors/               # Autonomous Behavior Engine
│   │   ├── base.py              # BaseBehavior interface and RobotContext
│   │   ├── manager.py           # Behavior registry & 10Hz control loop
│   │   ├── manual.py            # Manual teleop behavior (WASD, D-pad, API)
│   │   ├── wander.py            # Obstacle avoidance wander (reacts to bumpers/cliffs)
│   │   └── person_follower.py   # Vision-ready person follower stub (proportional steering)
│   ├── perception/              # Camera & Perception Pipeline
│   │   └── camera.py            # Camera sources (Pi Camera / USB / Mock) & target injection
│   └── web/                     # FastAPI Web Application
│       └── app.py               # REST API & WebSocket telemetry streaming
├── scripts/                     # CLI Entrypoints
│   ├── run_server.py            # Web server runner (`python scripts/run_server.py`)
│   ├── teleop_cli.py            # Interactive WASD terminal teleop
│   └── verify.py                # Hardware connection and sensor diagnostics
├── static/                      # Modern Web Cockpit UI (HTML5 / CSS3 / Vanilla JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── deploy/                      # Deployment Tooling
│   ├── Dockerfile               # Multi-arch container (Raspberry Pi ARM64/ARMv7 & x86)
│   ├── docker-compose.yml       # Docker compose with serial & camera passthrough
│   └── roomba.service           # Linux systemd service for auto-start on Pi boot
├── tests/                       # Automated Test Suite (23 unit & integration tests)
├── pyproject.toml               # Modern packaging metadata
└── requirements.txt             # Python dependencies
```

> **Backward Compatibility:** Legacy root entrypoints ([`web_server.py`](web_server.py), [`teleop_wasd.py`](teleop_wasd.py), [`verify_connection.py`](verify_connection.py), [`roomba_client.py`](roomba_client.py), etc.) are maintained as lightweight shims delegating directly to the modular architecture.

---

## 2. Hardware & Connection Overview

- **Port:** Motherboard micro-USB port (beneath dust bin / top faceplate).
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
git clone https://github.com/duck-5/CrazyRoomba.git
cd CrazyRoomba
pip install -r requirements.txt
```

### B. Raspberry Pi (Bare-Metal Linux)
On Raspberry Pi OS (Debian bookworm/bullseye), grant your user serial port access:
```bash
# Add current user to dialout and video groups for serial and camera access
sudo usermod -a -G dialout,video $USER

# Install Python requirements
pip install -r requirements.txt
```
*(Log out and back in once for group permissions to take effect).*

---

## 4. Running the Controller

### A. Web Server Cockpit (Recommended)
Launch the server to access the live cockpit dashboard:

```bash
# Standard launch (auto-discovers Roomba port):
python scripts/run_server.py --port 8000

# Or launch directly in offline mock simulation:
python scripts/run_server.py --mock

# Backward compatibility alias:
python web_server.py --port 8000
```

Open your browser to: **[http://localhost:8000](http://localhost:8000)** (or `http://<pi-ip>:8000` from any device on your local network).

#### Web Cockpit Features:
1. **Interactive SVG Telemetry:**
   - Real-time Left/Right Bumper indicators (glow red when pressed).
   - Real-time Wheel Drop indicators (glow amber when lifted).
   - 4 Floor Cliff sensors with reflection levels.
   - 6-zone Light Bumper IR proximity array.
   - Battery meter with dynamic gradient, voltage, current draw, and temperature.
   - Wheel encoders, distance, and angle odometry.
2. **Autonomous Behaviors Panel:**
   - Switch between **Manual**, **Wander (Obstacle Avoidance)**, and **Person Follower (Vision)** directly from the UI.
   - Displays real-time status and active behavior indicators.
3. **Safety & Arming Interlock:**
   - **ARM / DISARM:** Drive commands are locked out while DISARMED.
   - **E-STOP:** Spacebar or UI button immediately halts drive motors and disarms the robot.
   - **Dead-Man Switch:** Auto-halts motors if control pulses stop for > 500ms.
4. **Teleoperation:**
   - WASD Keyboard controls (`W`=Forward, `S`=Back, `A`=Left, `D`=Right, `Space`=E-Stop).
   - Touch/Mouse Virtual D-Pad.
   - Speed presets (100, 150, 250, 400 mm/s) and discrete nudge buttons.
5. **Sound & Music Synthesizer:**
   - Plays preset melodies (Mario, Star Wars Imperial March, Zelda, Charge), RTTTL ringtones, and Morse code audio beeps.

---

### B. Command-Line Teleoperation (WASD)
Drive the robot directly from a terminal over SSH or local prompt:

```bash
python scripts/teleop_cli.py
# Or legacy: python teleop_wasd.py
```
- Use `W`, `A`, `S`, `D` to drive.
- `+` / `-` to adjust speed.
- `Space` for emergency stop.
- `Q` or `Esc` to safely park and exit.

---

### C. Hardware Connection Diagnostics
Scan and verify connectivity and read sensor telemetry:

```bash
python scripts/verify.py
# Or legacy: python verify_connection.py
```

---

## 5. Deployment on Raspberry Pi

### Option A: Systemd Auto-Start Daemon
To start the Roomba controller automatically when the Raspberry Pi powers on:

1. Edit [`deploy/roomba.service`](deploy/roomba.service) to match your Pi username and directory path (default: `/home/pi/roomba-controller`).
2. Copy the service unit and enable it:
   ```bash
   sudo cp deploy/roomba.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable roomba.service
   sudo systemctl start roomba.service
   ```
3. Check service status or live logs:
   ```bash
   sudo systemctl status roomba.service
   journalctl -u roomba.service -f
   ```

---

### Option B: Docker & Docker Compose
A multi-stage multi-arch Docker container is provided for containerized operation.

1. Build the container:
   ```bash
   docker compose -f deploy/docker-compose.yml build
   ```
2. Run container with USB serial and camera passthrough:
   ```bash
   docker compose -f deploy/docker-compose.yml up -d
   ```
3. Check container logs:
   ```bash
   docker compose -f deploy/docker-compose.yml logs -f
   ```

---

## 6. Autonomous Behaviors & Vision Integration

### Adding a Custom Behavior Script
Behaviors run inside an isolated control loop managed by `BehaviorManager`. To implement a new behavior:

1. Create a class inheriting from `roomba.behaviors.base.BaseBehavior`:
```python
from roomba.behaviors.base import BaseBehavior, RobotContext
from roomba.core.state import DriveCommand

class LineFollowBehavior(BaseBehavior):
    name = "line_follower"
    description = "Follows ground line markers using cliff sensors"

    async def step(self, ctx: RobotContext) -> DriveCommand:
        # ctx.sensors contains all live Roomba telemetry
        # Return DriveCommand(left_speed, right_speed)
        return DriveCommand(150, 150)
```

2. Register your behavior with the controller in [`roomba/core/controller.py`](roomba/core/controller.py):
```python
self.behavior_manager.register(LineFollowBehavior())
```

3. Activate it via the Web UI or REST API:
```bash
curl -X POST http://localhost:8000/api/behaviors/start -H "Content-Type: application/json" -d '{"behavior":"line_follower"}'
```

---

### Vision & Person Following Pipeline
The person-following subsystem is pre-architected with:
- **`roomba.perception.camera.BaseCameraSource`**: Abstract camera interface supporting Picamera2, USB OpenCV, or Mock frame generation.
- **REST Target Injection Endpoint (`POST /api/perception`)**: Feed bounding boxes from external object detection models (YOLO, MediaPipe, MobileNet):
  ```json
  {
    "target": {
      "target_person": {
        "x": 320,
        "y": 240,
        "width": 120,
        "height": 280,
        "confidence": 0.92
      }
    }
  }
  ```
- **Proportional Controller**: [`FollowPersonBehavior`](roomba/behaviors/person_follower.py) computes yaw offset from the bounding box horizontal center and steers the wheels proportionally to center and follow the target person.

---

## 7. Automated Testing

Run the comprehensive test suite (25 tests covering driver protocol, mock hardware, safety state machine, persistent wheel odometry, behavior arbitration, REST APIs, WebSocket streaming, and sound synthesis):

```powershell
pytest -v
```

---

## 8. License & Attribution

Developed for the iRobot Roomba 960 Open Interface (OI) v2 specification.
Released under the Apache 2.0 License. See [LICENSE](LICENSE) for full terms.
