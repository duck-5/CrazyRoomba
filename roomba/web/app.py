"""
FastAPI Web Server for Roomba 960.
Provides REST and WebSocket endpoints for telemetry visualization,
mode control, ARM/DISARM, and pluggable autonomous behaviors.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from roomba.core.controller import RobotController
from roomba.driver.discovery import list_serial_ports
from roomba.config import config, STATIC_DIR

logger = logging.getLogger("roomba.web.app")

controller = RobotController()

startup_options: Dict[str, Any] = {
    "mock": False,
    "serial_port": None,
    "auto_connect": False,
    "init_vision": False,
}


def configure_startup(
    mock: bool = False,
    serial_port: Optional[str] = None,
    auto_connect: bool = False,
    init_vision: bool = True,
) -> None:
    """Configure hardware initialization to run inside FastAPI's live event loop."""
    startup_options["mock"] = mock
    startup_options["serial_port"] = serial_port
    startup_options["auto_connect"] = auto_connect
    startup_options["init_vision"] = init_vision


# --- Pydantic Request Models ---

class ConnectRequest(BaseModel):
    port: Optional[str] = None
    baud: int = 115200
    mock: bool = False
    mode: str = "Safe"


class ModeRequest(BaseModel):
    mode: str = Field(..., description="Target mode: safe, full, passive, off")


class DriveRequest(BaseModel):
    left: int = Field(..., ge=-500, le=500, description="Left wheel speed in mm/s")
    right: int = Field(..., ge=-500, le=500, description="Right wheel speed in mm/s")


class BehaviorRequest(BaseModel):
    behavior: str = Field(..., description="Behavior name: wander, follow_person, etc.")
    params: Optional[Dict[str, Any]] = None


class PerceptionRequest(BaseModel):
    target: Dict[str, Any] = Field(..., description="Perception detections / targets dictionary")


class NudgeRequest(BaseModel):
    left: int = Field(..., ge=-500, le=500, description="Left wheel speed in mm/s")
    right: int = Field(..., ge=-500, le=500, description="Right wheel speed in mm/s")
    duration_s: float = Field(0.5, ge=0.05, le=10.0, description="Duration in seconds")


class ActionRequest(BaseModel):
    action: str = Field(..., description="Action name: beep, tune, song, sound_mark, rtttl, morse, sos, clean, spot, dock, mock_sensor")
    note: Optional[int] = 72
    duration: Optional[int] = 16
    preset: Optional[str] = None
    song: Optional[str] = None
    mark: Optional[str] = None
    sound: Optional[str] = None
    notes: Optional[List[List[int]]] = None
    rtttl: Optional[str] = None
    text: Optional[str] = None
    dot_duration: Optional[int] = 6
    sensor: Optional[str] = None
    value: Optional[Any] = None


class SoundMarkRequest(BaseModel):
    mark: str = Field(..., description="Sound mark name: startup, shutdown, dock_success, clean_done, obstacle_alert, cliff_warning, low_battery, ack, nack, reverse_beep, happy, sad")


class ModeScriptRequest(BaseModel):
    mode: str = Field(..., description="Operating mode name: manual, wander, follow_person")


class CameraRetryRequest(BaseModel):
    device_index: Optional[int] = None
    mock: bool = False


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, description="English text to speak")
    rate: int = Field(165, ge=80, le=300, description="Speech rate in WPM")
    play_on_speaker: bool = True


class VoiceCommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, description="English voice transcript or command")
    execute: bool = True
    speak_reply: bool = True


class AIAskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="Natural language query or command for AI Brain")
    include_vision: bool = True
    execute: bool = True
    speak: bool = False


class VisionTargetRequest(BaseModel):
    target_class: str = Field(..., description="Target class: person, cat, dog, any")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if startup_options.get("mock"):
            await controller.connect(mock=True)
            await controller.vision.initialize(mock=True)
        else:
            if startup_options.get("auto_connect"):
                res = await controller.retry_connect(port=startup_options.get("serial_port"), mock=False)
                if not res.get("connected"):
                    logger.warning(f"Auto-connect failed: {res.get('error')}")
            if startup_options.get("init_vision"):
                cam_status = await controller.vision.initialize(mock=False)
                if not cam_status.get("available"):
                    logger.warning(f"Camera not detected on startup: {cam_status.get('error')}")
        try:
            yield
        finally:
            await controller.vision.stop()
            if controller.is_connected:
                await controller.disconnect()

    application = FastAPI(
        title="Roomba 960 Web Control Hub",
        description="Cross-platform Roomba 960 Controller (Raspberry Pi & Windows)",
        version="1.0.0",
        lifespan=lifespan,
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
        """Current robot status, armed state, telemetry, active behavior, camera & voice health."""
        return {
            "connected": controller.is_connected,
            "port": controller.port,
            "is_mock": controller.is_mock,
            "last_error": controller.last_error,
            "armed": controller.armed,
            "is_driving": controller.is_driving,
            "mode": controller.client.mode if controller.client else "Off",
            "active_behavior": controller.behavior_manager.active_name,
            "telemetry": controller.latest_telemetry,
            "event_log": controller.event_log[-20:],
            "camera": controller.vision.get_status(),
            "voice": controller.voice.get_status(),
            "ai": controller.ai_brain.get_status(),
            "pi_battery": controller.pi_battery.get_status(is_mock=controller.is_mock),
        }

    @application.get("/api/hardware/status")
    async def api_hardware_status():
        """Unified hardware health snapshot (Robot, Camera, Mic, Speakers, Pi Battery)."""
        return {
            "robot": {
                "connected": controller.is_connected,
                "port": controller.port,
                "is_mock": controller.is_mock,
                "error": controller.last_error if not controller.is_connected else None,
            },
            "camera": controller.vision.get_status(),
            "voice": controller.voice.get_status(),
            "ai": controller.ai_brain.get_status(),
            "pi_battery": controller.pi_battery.get_status(is_mock=controller.is_mock),
        }

    @application.get("/api/pi/battery")
    async def api_pi_battery():
        """Return Raspberry Pi battery / UPS / PMIC power telemetry."""
        return controller.pi_battery.get_status(is_mock=controller.is_mock)

    @application.post("/api/hardware/retry")
    async def api_hardware_retry():
        """Re-probe Robot serial, Camera, and Audio (Mic/Speaker) hardware."""
        robot_res = await controller.retry_connect() if not controller.is_connected else {
            "connected": True,
            "port": controller.port,
            "is_mock": controller.is_mock,
            "error": None,
        }
        cam_res = await controller.vision.retry()
        voice_res = controller.voice.retry()
        return {
            "robot": robot_res,
            "camera": cam_res,
            "voice": voice_res,
        }

    @application.post("/api/robot/retry")
    async def api_robot_retry():
        """Safely retry Roomba serial auto-detection and connection without crashing."""
        return await controller.retry_connect()

    @application.get("/api/map")
    async def api_map():
        """Returns the current 2D occupancy grid map."""
        return controller.grid_map.get_map_data()

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

    # --- Autonomous Operating Modes & Behaviors ---
    @application.get("/api/modes")
    async def api_list_modes():
        """List registered autonomous operating modes and active status."""
        return {
            "active": controller.mode_manager.active_name,
            "modes": controller.list_modes(),
        }

    @application.post("/api/modes/start")
    async def api_start_mode(req: ModeScriptRequest):
        """Switch to an autonomous operating mode script."""
        try:
            return await controller.set_operating_mode(req.mode)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/modes/stop")
    async def api_stop_mode():
        """Revert to manual operating mode."""
        await controller.mode_manager.stop_active()
        return {"status": "ok", "active_mode": "manual", "active_behavior": "manual"}

    @application.get("/api/behaviors")
    async def api_list_behaviors():
        """Backward-compatible alias for /api/modes."""
        return {
            "active": controller.behavior_manager.active_name,
            "behaviors": controller.list_behaviors(),
        }

    @application.post("/api/behaviors/start")
    async def api_start_behavior(req: BehaviorRequest):
        """Backward-compatible alias for /api/modes/start."""
        try:
            return await controller.set_behavior(req.behavior)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @application.post("/api/behaviors/stop")
    async def api_stop_behavior():
        """Backward-compatible alias for /api/modes/stop."""
        return await api_stop_mode()

    @application.post("/api/perception")
    async def api_inject_perception(req: PerceptionRequest):
        """Inject perception bounding box (e.g. from OpenCV camera pipeline)."""
        controller.set_perception_target(req.target)
        return {"status": "ok"}

    @application.get("/api/perception/status")
    async def api_perception_status():
        """Check if vision-dependent modes are active (Resource Management for Pi 5)."""
        active_mode = controller.mode_manager.active_name
        is_active = active_mode in ["follow_person", "pet_companion", "wander", "map_mode"]
        return {"vision_active": is_active, "mode": active_mode}

    # --- Camera & Person Vision Endpoints ---

    @application.get("/api/camera/status")
    async def api_camera_status():
        """Return camera connection status, error message, and person detection state."""
        return controller.vision.get_status()

    @application.post("/api/camera/retry")
    async def api_camera_retry(req: Optional[CameraRetryRequest] = None):
        """Re-probe and re-open the camera without crashing if unavailable."""
        device_idx = req.device_index if req else None
        mock = req.mock if req else False
        return await controller.vision.retry(mock=mock, device_index=device_idx)

    @application.post("/api/camera/mock")
    async def api_camera_mock():
        """Enable simulated mock camera with moving person detection."""
        return await controller.vision.initialize(mock=True)

    @application.post("/api/camera/stop")
    async def api_camera_stop():
        """Stop camera capture and release resources."""
        await controller.vision.stop()
        return controller.vision.get_status()

    @application.post("/api/camera/rotate")
    async def api_camera_rotate(rotation: Optional[int] = None):
        """Rotate camera feed (defaults to toggling 180°)."""
        next_rot = ((controller.vision.rotation + 180) % 360) if rotation is None else rotation
        controller.vision.set_rotation(next_rot)
        return controller.vision.get_status()

    @application.get("/api/camera/snapshot")
    async def api_camera_snapshot():
        """Return a single annotated JPEG frame from the camera."""
        jpeg = controller.vision.get_latest_jpeg()
        if jpeg is None:
            raise HTTPException(
                status_code=503,
                detail=controller.vision.error or "Camera frame unavailable.",
            )
        return Response(content=jpeg, media_type="image/jpeg")

    @application.get("/api/camera/stream")
    async def api_camera_stream():
        """Live MJPEG video stream with person detection bounding box overlay."""
        if not controller.vision.available:
            raise HTTPException(
                status_code=503,
                detail=controller.vision.error or "Camera not detected.",
            )

        async def frame_generator():
            last_seq = -1
            while controller.vision.available:
                seq, jpeg = await controller.vision.wait_next_jpeg(last_seq, timeout=0.5)
                if jpeg is not None and seq != last_seq:
                    last_seq = seq
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    )

        return StreamingResponse(
            frame_generator(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # --- English Voice (TTS & STT) Endpoints ---

    @application.get("/api/voice/status")
    async def api_voice_status():
        """Return English TTS/STT engine and microphone/speaker hardware status."""
        return controller.voice.get_status()

    @application.post("/api/voice/retry")
    async def api_voice_retry():
        """Re-probe microphone and speaker hardware without crashing."""
        return controller.voice.retry()

    @application.post("/api/voice/tts")
    async def api_voice_tts(req: TTSRequest):
        """Speak English text on Pi speakers (if connected) and/or provide browser audio."""
        res = await controller.voice.speak(
            req.text,
            rate=req.rate,
            play_on_speaker=req.play_on_speaker,
        )
        return res

    @application.get("/api/voice/tts/audio")
    async def api_voice_tts_audio(text: str, rate: int = 165):
        """Synthesize English text to WAV audio for browser playback."""
        wav_bytes = await controller.voice.synthesize_wav(text, rate=rate)
        if wav_bytes is None:
            raise HTTPException(
                status_code=501,
                detail="No server-side WAV TTS engine (espeak-ng/pyttsx3) installed. Use browser speechSynthesis fallback.",
            )
        return Response(content=wav_bytes, media_type="audio/wav")

    @application.post("/api/voice/command")
    async def api_voice_command(req: VoiceCommandRequest):
        """Process an English voice transcript, execute matched Roomba command, and return reply."""
        return await controller.voice.process_command_text(
            req.text,
            execute=req.execute,
            speak_reply=req.speak_reply,
        )

    @application.post("/api/voice/stt")
    async def api_voice_stt(
        audio: UploadFile = File(...),
        execute: bool = Form(True),
        speak_reply: bool = Form(True),
    ):
        """Transcribe uploaded English WAV audio and optionally execute Roomba command."""
        wav_bytes = await audio.read()
        return await controller.voice.process_audio_wav(
            wav_bytes,
            execute=execute,
            speak_reply=speak_reply,
        )

    # --- Physical AI & LLM Brain Endpoints ---

    @application.get("/api/ai/status")
    async def api_ai_status():
        """Return Physical AI Brain provider, model, capabilities, and history."""
        return controller.ai_brain.get_status()

    @application.post("/api/ai/ask")
    async def api_ai_ask(req: AIAskRequest):
        """Process natural language query via Gemini VLM / Ollama / Local Physical AI engine."""
        res = await controller.ai_brain.ask(
            query=req.query,
            include_vision=req.include_vision,
            execute=req.execute,
        )
        if req.speak and res.get("reply"):
            try:
                await controller.voice.speak(res["reply"], play_on_speaker=True)
            except Exception as e:
                logger.debug(f"AI TTS speak warning: {e}")
        return res

    @application.post("/api/ai/scene")
    async def api_ai_scene(prompt: Optional[str] = None):
        """Trigger multimodal visual scene analysis on the live camera view."""
        p = prompt or "Describe the room and identify any people, cats, or obstacles"
        return await controller.ai_brain.analyze_scene(prompt=p)

    @application.post("/api/vision/target")
    async def api_set_vision_target(req: VisionTargetRequest):
        """Switch vision tracking target class ('person', 'cat', 'dog', 'any')."""
        controller.vision.set_target_class(req.target_class)
        return controller.vision.get_status()

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
                preset=req.preset or req.song,
                song=req.song or req.preset,
                mark=req.mark or req.sound,
                sound=req.sound or req.mark,
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
        """Return available 8-bit songs, sound marks, and sample RTTTL ringtone strings."""
        return controller.get_sound_presets()

    @application.post("/api/sound/play")
    async def api_sound_play(req: ActionRequest):
        """Play a tune, custom song, RTTTL string, Morse code, or beep."""
        return await api_action(req)

    @application.post("/api/sound/mark")
    async def api_sound_mark(req: SoundMarkRequest):
        """Play a robot acoustic sound mark / earcon."""
        try:
            return await controller.execute_action("sound_mark", mark=req.mark)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


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
