"""
Comprehensive tests for Physical AI, Cat / Pet Detection,
Vision-Assisted Obstacle Avoidance, PetCompanionMode, and AIBrainService (LLM/VLM).
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from roomba.web.app import create_app, controller
from roomba.perception.classes import (
    COCO_CLASSES,
    VOC_CLASSES,
    nms_boxes,
    get_color_for_label,
)
from roomba.perception.vision import VisionService
from roomba.modes.base import RobotContext
from roomba.modes.pet_companion import PetCompanionMode
from roomba.modes.wander import WanderMode
from roomba.ai.brain import AIBrainService


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_nms_boxes_logic():
    """Verify greedy NMS suppresses overlapping boxes and preserves non-overlapping boxes."""
    # 1. Empty input
    assert nms_boxes([], []) == []

    # 2. Fully identical overlapping boxes (one high score, one low)
    boxes = [(10, 10, 50, 50), (10, 10, 50, 50)]
    scores = [0.95, 0.50]
    keep = nms_boxes(boxes, scores, iou_threshold=0.45)
    assert keep == [0]

    # 3. Two separated boxes (both kept)
    boxes = [(10, 10, 40, 40), (100, 100, 40, 40)]
    scores = [0.85, 0.80]
    keep = nms_boxes(boxes, scores, iou_threshold=0.45)
    assert sorted(keep) == [0, 1]

    # 4. Color lookup
    assert get_color_for_label("cat") == (0, 165, 255)
    assert get_color_for_label("dog") == (255, 178, 50)
    assert get_color_for_label("person") == (0, 230, 118)
    assert get_color_for_label("unknown_thing") == (180, 180, 180)


def test_per_class_nms_preserves_overlapping_distinct_categories():
    """Verify per-class NMS preserves overlapping boxes of different classes (e.g. Person + Cat)."""
    # Box 0: Person (0, 0, 100, 100), score 0.92, class 0
    # Box 1: Person duplicate (3, 3, 95, 95), score 0.65, class 0 (should be suppressed)
    # Box 2: Cat on lap (10, 10, 80, 80), score 0.88, class 15 (should NOT be suppressed by Person!)
    boxes = [(0, 0, 100, 100), (3, 3, 95, 95), (10, 10, 80, 80)]
    scores = [0.92, 0.65, 0.88]
    class_ids = [0, 0, 15]

    # With class_ids: duplicate person box 1 suppressed, cat box 2 preserved!
    keep_with_classes = nms_boxes(boxes, scores, iou_threshold=0.45, class_ids=class_ids)
    assert 0 in keep_with_classes
    assert 2 in keep_with_classes
    assert 1 not in keep_with_classes
    assert len(keep_with_classes) == 2

    # Without class_ids (class-agnostic): cat box 2 would be wiped out
    keep_agnostic = nms_boxes(boxes, scores, iou_threshold=0.45)
    assert keep_agnostic == [0]


def test_yolox_coco_multi_object_cat_and_person_detection():
    """Verify YOLOX detector identifies both cat (COCO 15) and person (COCO 0)."""
    vs = VisionService()
    vs._init_yolox_anchors()

    fake_cv2 = MagicMock()
    fake_cv2.IMWRITE_JPEG_QUALITY = 1
    fake_cv2.FONT_HERSHEY_SIMPLEX = 0
    fake_cv2.INTER_LINEAR = 1
    fake_cv2.ROTATE_180 = 1
    fake_cv2.rotate.side_effect = lambda f, code: f
    fake_cv2.resize.side_effect = lambda f, sz, **kw: np.zeros((sz[1], sz[0], 3), dtype=np.uint8)
    fake_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

    outs = np.zeros((1, 8400, 85), dtype=np.float32)

    # Anchor 0: Person (class 0 -> column 5)
    outs[0, 0, 0] = 40.0
    outs[0, 0, 1] = 30.0
    outs[0, 0, 2] = np.log(200.0 / 8.0)
    outs[0, 0, 3] = np.log(300.0 / 8.0)
    outs[0, 0, 4] = 0.90  # objectness
    outs[0, 0, 5] = 0.95  # person

    # Anchor 1: Cat (class 15 -> column 5 + 15 = 20)
    outs[0, 1, 0] = 20.0
    outs[0, 1, 1] = 25.0
    outs[0, 1, 2] = np.log(120.0 / 8.0)
    outs[0, 1, 3] = np.log(140.0 / 8.0)
    outs[0, 1, 4] = 0.88  # objectness
    outs[0, 1, 20] = 0.92  # cat

    fake_net = MagicMock()
    fake_net.getUnconnectedOutLayersNames.return_value = ["output"]
    fake_net.forward.return_value = [outs]

    vs._cv2 = fake_cv2
    vs._yolox_net = fake_net
    vs.detector_backend = "yolox-coco"

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target, jpeg = vs._process_real_frame_sync(frame)

    assert target is not None
    assert vs.person_detected is True
    assert vs.target_person is not None
    assert vs.target_person["label"] == "person"
    assert vs.cat_detected is True
    assert vs.target_cat is not None
    assert vs.target_cat["label"] == "cat"
    assert len(vs.detected_objects) >= 2

    # Switch target to cat
    vs.set_target_class("cat")
    target_cat, _ = vs._process_real_frame_sync(frame)
    assert target_cat is not None
    assert target_cat["label"] == "cat"


def test_mobilenet_ssd_cat_and_person_detection():
    """Verify MobileNet-SSD detects both cat (class 8) and person (class 15)."""
    vs = VisionService()
    fake_cv2 = MagicMock()
    fake_cv2.IMWRITE_JPEG_QUALITY = 1
    fake_cv2.FONT_HERSHEY_SIMPLEX = 0
    fake_cv2.ROTATE_180 = 1
    fake_cv2.rotate.side_effect = lambda f, code: f
    fake_cv2.resize.side_effect = lambda f, sz: np.zeros((sz[1], sz[0], 3), dtype=np.uint8)
    fake_cv2.dnn.blobFromImage.return_value = np.zeros((1, 3, 300, 300), dtype=np.float32)
    fake_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

    fake_net = MagicMock()
    # Detection 0: Person (class 15), Detection 1: Cat (class 8)
    det = np.array([[[
        [0.0, 15.0, 0.89, 0.2, 0.1, 0.6, 0.9],
        [0.0, 8.0, 0.84, 0.1, 0.5, 0.3, 0.8],
    ]]], dtype=np.float32)
    fake_net.forward.return_value = det

    vs._cv2 = fake_cv2
    vs._ssd_net = fake_net
    vs.detector_backend = "mobilenet-ssd"

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target, jpeg = vs._process_real_frame_sync(frame)

    assert vs.person_detected is True
    assert vs.cat_detected is True
    assert vs.target_cat is not None
    assert vs.target_cat["label"] == "cat"
    assert vs.target_cat["confidence"] == 0.84


@pytest.mark.asyncio
async def test_pet_companion_mode_navigation_and_playful_retreat():
    """Verify PetCompanionMode tracks cat, backs away playfully when cat approaches, and maintains safety."""
    ctrl = controller
    mode = PetCompanionMode(
        safe_bbox_width=0.25,
        retreat_bbox_width=0.38,
        forward_speed=120,
    )

    # 1. Cat far away (bbox_width = 0.15) -> drive forward gently
    ctx_far = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {}},
        perception={"target_cat": {"x_center": 0.5, "bbox_width": 0.15, "confidence": 0.85}},
    )
    cmd_far = await mode.update(ctx_far)
    assert cmd_far.left > 0 and cmd_far.right > 0
    assert abs(cmd_far.left - cmd_far.right) <= 5

    # 2. Cat to the right (x_center = 0.8) -> steer right
    ctx_right = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {}},
        perception={"target_cat": {"x_center": 0.8, "bbox_width": 0.20, "confidence": 0.85}},
    )
    cmd_right = await mode.update(ctx_right)
    assert cmd_right.left > cmd_right.right

    # 3. Cat comes very close (bbox_width = 0.45 > retreat_bbox_width 0.38) -> playful retreat (reverse!)
    ctx_close = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {}},
        perception={"target_cat": {"x_center": 0.5, "bbox_width": 0.45, "confidence": 0.90}},
    )
    cmd_close = await mode.update(ctx_close)
    assert cmd_close.left < 0
    assert cmd_close.right < 0  # Reversing playfully away from stalking cat!

    # 4. Emergency bump -> halt
    ctx_bump = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {"bump_left": True}},
        perception={"target_cat": {"x_center": 0.5, "bbox_width": 0.20, "confidence": 0.90}},
    )
    cmd_bump = await mode.update(ctx_bump)
    assert cmd_bump.left == 0 and cmd_bump.right == 0


@pytest.mark.asyncio
async def test_wander_mode_proactive_ir_and_vision_avoidance():
    """Verify WanderMode steers away on IR light bumper or vision obstacles before physical bumper hit."""
    ctrl = controller
    wander = WanderMode(cruise_speed=150)

    # 1. Clear ahead
    ctx_clear = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {}},
        perception={},
    )
    cmd_clear = await wander.update(ctx_clear)
    assert cmd_clear.left == 150 and cmd_clear.right == 150

    # 2. IR light bumper center obstacle -> proactive turn before physical impact
    ctx_ir = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {"center_left": True}},
        perception={},
    )
    cmd_ir = await wander.update(ctx_ir)
    assert cmd_ir.left != cmd_ir.right  # Spinning/turning away before crash!

    # 3. Vision obstacle (chair right in front) -> proactive steer
    wander._state = "FORWARD"
    ctx_vis = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {}},
        perception={
            "detected_objects": [
                {"label": "chair", "bbox_width": 0.35, "x_center": 0.5, "confidence": 0.85}
            ]
        },
    )
    cmd_vis = await wander.update(ctx_vis)
    assert cmd_vis.left != cmd_vis.right


@pytest.mark.asyncio
async def test_pet_companion_mode_tracks_configured_dog():
    """Verify PetCompanionMode with target_species='dog' tracks dog even if cat is also present."""
    ctrl = controller
    mode = PetCompanionMode(target_species="dog", safe_bbox_width=0.25)

    # Cat is to the left (x=0.2), Dog is to the right (x=0.8)
    ctx_dog = RobotContext(
        controller=ctrl,
        telemetry={"bumps_and_drops": {}, "light_bumpers": {}},
        perception={
            "target_cat": {"x_center": 0.2, "bbox_width": 0.20, "confidence": 0.90},
            "target_dog": {"x_center": 0.8, "bbox_width": 0.20, "confidence": 0.85},
            "detected_objects": [
                {"label": "cat", "x_center": 0.2, "bbox_width": 0.20, "confidence": 0.90},
                {"label": "dog", "x_center": 0.8, "bbox_width": 0.20, "confidence": 0.85},
            ],
        },
    )
    cmd = await mode.update(ctx_dog)
    # Target dog is on the right (x=0.8 > 0.5), so robot must steer right (left speed > right speed)
    assert cmd.left > cmd.right


@pytest.mark.asyncio
async def test_wander_mode_cliff_in_turn_and_backup_states():
    """Verify WanderMode immediately halts and backs away from cliff even during TURN state."""
    ctrl = controller
    wander = WanderMode(cruise_speed=150)

    # Put robot in TURN state
    wander._state = "TURN"
    wander._state_timer = 99999999.0

    # A cliff is suddenly detected during the turn
    ctx_cliff = RobotContext(
        controller=ctrl,
        telemetry={"cliffs": {"cliff_front_left": True}, "bumps_and_drops": {}, "light_bumpers": {}},
        perception={},
    )
    cmd = await wander.update(ctx_cliff)
    # Must immediately transition to BACKUP and drive backwards, not continue turning off the cliff!
    assert wander._state == "BACKUP"
    assert cmd.left < 0 and cmd.right < 0


@pytest.mark.asyncio
async def test_ai_brain_local_and_scene_summary():
    """Verify AIBrainService local intent resolution, scene summary, and action execution."""
    brain = AIBrainService(controller=controller)

    # 1. Status check
    st = brain.get_status()
    assert st["available"] is True
    assert "capabilities" in st

    # 2. Scene summary with cat
    summary = brain._generate_local_scene_summary([
        {"label": "cat", "confidence": 0.91, "bbox": [10, 10, 50, 50]},
        {"label": "chair", "confidence": 0.75, "bbox": [80, 80, 100, 100]},
    ])
    assert "cat" in summary.lower()
    assert "91%" in summary

    # 3. Ask "follow my cat" -> routes to mode_pet
    res = await brain.ask("follow my cat", include_vision=False, execute=True)
    assert res["ok"] is True
    assert res["intent"] == "mode_pet"
    assert "pet companion" in res["reply"].lower()
    assert controller.mode_manager.active_name == "pet_companion"

    # 4. Ask "status"
    res_st = await brain.ask("what is your status and battery", include_vision=False, execute=False)
    assert res_st["ok"] is True
    assert "battery" in res_st["reply"].lower()


@pytest.mark.asyncio
async def test_ai_brain_gemini_multimodal_mock():
    """Verify AIBrainService uses Gemini VLM when API key and SDK are available."""
    brain = AIBrainService(controller=controller)
    brain.gemini_api_key = "fake-key-for-test"
    brain.provider = "gemini"

    fake_response = MagicMock()
    fake_response.text = "I observe a spacious room with a cat resting in the center and a chair to the right."

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("roomba.ai.brain._GENAI_AVAILABLE", True), \
         patch("roomba.ai.brain.genai.Client", return_value=fake_client):
        res = await brain.analyze_scene("Describe the room")
        assert res["ok"] is True
        assert res["provider"] == "gemini"
        assert "cat resting" in res["description"]


def test_api_ai_and_vision_endpoints(client):
    """Verify FastAPI endpoints for Physical AI status, ask, scene, and vision target."""
    client.post("/api/connect", json={"mock": True})

    # GET /api/ai/status
    res = client.get("/api/ai/status")
    assert res.status_code == 200
    assert res.json()["available"] is True

    # POST /api/vision/target
    vt = client.post("/api/vision/target", json={"target_class": "cat"})
    assert vt.status_code == 200
    assert vt.json()["target_class"] == "cat"

    # POST /api/ai/ask
    ask_res = client.post("/api/ai/ask", json={"query": "explore the house", "execute": True, "speak": False})
    assert ask_res.status_code == 200
    data = ask_res.json()
    assert data["ok"] is True
    assert data["intent"] == "mode_wander"
    assert controller.mode_manager.active_name == "wander"

    # POST /api/ai/scene
    scene_res = client.post("/api/ai/scene")
    assert scene_res.status_code == 200
    assert "description" in scene_res.json()

    # Voice command for cat
    vc = client.post("/api/voice/command", json={"text": "follow cat", "execute": True, "speak_reply": False})
    assert vc.status_code == 200
    assert vc.json()["intent"] == "mode_pet"
    assert controller.mode_manager.active_name == "pet_companion"

    # Voice command for dog
    vc_dog = client.post("/api/voice/command", json={"text": "target dog", "execute": True, "speak_reply": False})
    assert vc_dog.status_code == 200
    assert vc_dog.json()["intent"] == "target_dog"
    assert controller.vision.target_class == "dog"

    # Perception status reports active for pet_companion
    ps = client.get("/api/perception/status")
    assert ps.status_code == 200
    assert ps.json()["vision_active"] is True

    client.post("/api/disconnect")


@pytest.mark.asyncio
async def test_ai_brain_gemini_async_client_non_blocking():
    """Verify AIBrainService uses async client.aio.models when available."""
    brain = AIBrainService(controller=controller)
    brain.gemini_api_key = "fake-key"
    brain.provider = "gemini"

    fake_response = MagicMock()
    fake_response.text = "All clear in front. [ACTION:mode_wander]"

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch("roomba.ai.brain._GENAI_AVAILABLE", True), \
         patch("roomba.ai.brain.genai.Client", return_value=fake_client):
        res = await brain.ask("start wandering", include_vision=False, execute=True)
        assert res["ok"] is True
        assert res["intent"] == "mode_wander"
        assert res["executed"] is True
        assert "[ACTION:" not in res["reply"]
        assert controller.mode_manager.active_name == "wander"


@pytest.mark.asyncio
async def test_ai_brain_ollama_provider_integration():
    """Verify AIBrainService queries Ollama HTTP endpoint when provider is ollama."""
    brain = AIBrainService(controller=controller)
    brain.provider = "ollama"

    fake_resp_data = {"response": "The room has a cat sitting by the couch. [ACTION:mode_pet,species:cat]"}
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = fake_resp_data

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value.post = AsyncMock(return_value=mock_post_res)

    with patch("roomba.ai.brain.httpx.AsyncClient", return_value=mock_async_client):
        # 1. Ask query with action extraction
        res = await brain.ask("play with my cat", include_vision=False, execute=True)
        assert res["ok"] is True
        assert res["provider"] == "ollama"
        assert res["intent"] == "mode_pet"
        assert res["executed"] is True
        assert "[ACTION:" not in res["reply"]
        assert controller.mode_manager.active_name == "pet_companion"

        # 2. Scene analysis with Ollama
        scene_res = await brain.analyze_scene("Describe surroundings")
        assert scene_res["ok"] is True
        assert scene_res["provider"] == "ollama"
        assert "cat sitting" in scene_res["description"]
