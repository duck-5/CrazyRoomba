"""
FastAPI Web Server for Roomba 960.
Provides REST and WebSocket endpoints for telemetry visualization,
mode control, ARM/DISARM, and pluggable autonomous behaviors.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from roomba.core.controller import RobotController
from roomba.driver.discovery import list_serial_ports
from roomba.config import config, STATIC_DIR

logger = logging.getLogger("roomba.web.app")

controller = RobotController()


# --- Pydantic Request Models ---

class ConnectRequest(BaseModel):
    port: Optional[str] = None
    mock: bool = False
    mode: Optional[str] = "Safe"


class ModeRequest(BaseModel):
    mode: str = Field(..., description="Target OI Mode: safe, full, passive, off")


class BehaviorRequest(BaseModel):
    behavior: str = Field(..., description="Target behavior name (e.g. manual, wander, follow_person)")


class PerceptionRequest(BaseModel):
    target: Dict[str, Any] = Field(..., description="Target perception payload, e.g. target_person")


class DriveRequest(BaseModel):
    left: int = Field(..., ge=-500, le=500, description="Left wheel speed in mm/s")
    right: int = Field(..., ge=-500, le=500, description="Right wheel speed in mm/s")


class NudgeRequest(BaseModel):
    left: int = Field(..., ge=-500, le=500, description="Left wheel speed in mm/s")
    right: int = Field(..., ge=-500, le=500, description="Right wheel speed in mm/s")
    duration_s: float = Field(0.5, ge=0.05, le=10.0, description="Duration in seconds")


class ActionRequest(BaseModel):
    action: str = Field(..., description="Action name: beep, tune, song, rtttl, morse, sos, human, vocal, clean, spot, dock, mock_sensor")
    note: Optional[int] = 72
    duration: Optional[int] = 16
    preset: Optional[str] = None
    sound: Optional[str] = None
    notes: Optional[List[List[int]]] = None
    rtttl: Optional[str] = None
    text: Optional[str] = None
    dot_duration: Optional[int] = 6
    sensor: Optional[str] = None
    value: Optional[Any] = None


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    application = FastAPI(
        title="Roomba 960 Web Control Hub",
        description="Cross-platform Roomba 960 Controller (Raspberry Pi & Windows)",
        version="1.0.0",
    )

    if STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @application.get("/", response_class=HTMLResponse)
    async def index():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse("<h1>Roomba Web Hub</h1><p>static/index.html not found.</p>")

    @application.get("/api/ports")
    async def api_list_ports():
        """List serial ports matching Roomba on Windows (COM*) or Linux (/dev/tty*)."""
        return {"ports": list_serial_ports()}

    @application.get("/api/status")
    async def api_status():
        """Current robot status, armed state, telemetry, and active behavior."""
        return {
            "connected": controller.is_connected,
            "port": controller.port,
            "is_mock": controller.is_mock,
            "armed": controller.armed,
            "is_driving": controller.is_driving,
            "mode": controller.client.mode if controller.client else "Off",
            "active_behavior": controller.behavior_manager.active_name,
            "telemetry": controller.latest_telemetry,
            "event_log": controller.event_log[-20:],
        }

    @application.post("/api/connect")
    async def api_connect(req: ConnectRequest):
        try:
            if req.mode:
                controller.default_mode = req.mode
            res = await controller.connect(port=req.port, mock=req.mock)
            return res
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/disconnect")
    async def api_disconnect():
        return await controller.disconnect()

    @application.post("/api/arm")
    async def api_arm():
        try:
            return controller.arm()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/disarm")
    async def api_disarm():
        return controller.disarm()

    @application.post("/api/estop")
    async def api_estop():
        return await controller.emergency_stop()

    @application.post("/api/mode")
    async def api_mode(req: ModeRequest):
        try:
            return await controller.set_mode(req.mode)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- Behaviors Endpoints ---

    @application.get("/api/behaviors")
    async def api_list_behaviors():
        """List registered autonomous behaviors and active status."""
        return {
            "active": controller.behavior_manager.active_name,
            "behaviors": controller.list_behaviors(),
        }

    @application.post("/api/behaviors/start")
    async def api_start_behavior(req: BehaviorRequest):
        """Switch to an autonomous behavior script."""
        try:
            return await controller.set_behavior(req.behavior)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/behaviors/stop")
    async def api_stop_behavior():
        """Revert to manual teleop behavior."""
        await controller.behavior_manager.stop_active()
        return {"status": "ok", "active_behavior": "manual"}

    @application.post("/api/perception")
    async def api_inject_perception(req: PerceptionRequest):
        """Inject perception bounding box (e.g. from OpenCV camera pipeline)."""
        controller.set_perception_target(req.target)
        return {"status": "ok"}

    # --- Drive Endpoints ---

    @application.post("/api/drive")
    async def api_drive(req: DriveRequest):
        try:
            return await controller.drive(req.left, req.right)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/stop")
    async def api_stop():
        if controller.is_connected and controller.client:
            await controller.client.stop()
            controller.is_driving = False
        return {"status": "stopped"}

    @application.post("/api/nudge")
    async def api_nudge(req: NudgeRequest):
        try:
            return await controller.nudge(req.left, req.right, req.duration_s)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/action")
    async def api_action(req: ActionRequest):
        try:
            return await controller.execute_action(
                req.action,
                note=req.note,
                duration=req.duration,
                preset=req.preset,
                sound=req.sound,
                notes=req.notes,
                rtttl=req.rtttl,
                text=req.text,
                dot_duration=req.dot_duration,
                sensor=req.sensor,
                value=req.value,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.get("/api/sound/presets")
    async def api_sound_presets():
        """Return available preset tunes and sample RTTTL ringtone strings."""
        return controller.get_sound_presets()

    @application.post("/api/sound/play")
    async def api_sound_play(req: ActionRequest):
        """Play a tune, custom song, RTTTL string, Morse code, or beep."""
        return await api_action(req)

    @application.post("/api/odometry/reset")
    async def api_reset_odometry():
        """Reset cumulative odometry distance and heading counters."""
        return controller.reset_odometry()

    # --- WebSocket Channel ---

    @application.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        controller.register_subscriber(websocket)

        if controller.latest_telemetry:
            await websocket.send_json(controller.latest_telemetry)

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "client_ts": data.get("ts")})

                elif msg_type == "drive":
                    left = int(data.get("left", 0))
                    right = int(data.get("right", 0))
                    try:
                        await controller.drive(left, right)
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": str(e)})

                elif msg_type == "stop":
                    if controller.is_connected and controller.client:
                        await controller.client.stop()
                        controller.is_driving = False

                elif msg_type == "arm":
                    try:
                        controller.arm()
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": str(e)})

                elif msg_type == "disarm":
                    controller.disarm()

                elif msg_type == "estop":
                    await controller.emergency_stop()

                elif msg_type == "mode":
                    mode = data.get("mode", "safe")
                    try:
                        await controller.set_mode(mode)
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": str(e)})

                elif msg_type == "behavior":
                    beh = data.get("behavior", "manual")
                    try:
                        await controller.set_behavior(beh)
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": str(e)})

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected.")
        except Exception as e:
            logger.warning(f"WebSocket error: {e}")
        finally:
            controller.unregister_subscriber(websocket)

    return application


app = create_app()
