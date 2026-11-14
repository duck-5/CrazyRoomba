"""
Object Detection Class Definitions and Pure-Python NMS for CrazyRoomba.
Supports 80-class COCO (YOLOX ONNX) and 21-class PASCAL VOC (MobileNet-SSD).
"""

from __future__ import annotations
from typing import List, Tuple, Dict, Any

# COCO 80-Class Labels (YOLOX ONNX)
COCO_CLASSES: List[str] = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]

# PASCAL VOC 21-Class Labels (MobileNet-SSD Caffe)
VOC_CLASSES: List[str] = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car",
    "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person",
    "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]

# Semantic Categories for Physical AI Decision-Making
PET_LABELS = {"cat", "dog", "bird"}
PERSON_LABELS = {"person"}
OBSTACLE_LABELS = {
    "chair", "couch", "sofa", "dining table", "diningtable", "bed", "toilet",
    "tv", "tvmonitor", "refrigerator", "bench", "potted plant", "pottedplant", "table"
}
ITEM_LABELS = {
    "bottle", "cup", "sports ball", "backpack", "book", "teddy bear", "cell phone", "remote"
}

# Color palette for HUD visualization (BGR format for OpenCV)
LABEL_COLORS: Dict[str, Tuple[int, int, int]] = {
    "person": (0, 230, 118),       # Bright Emerald Green
    "cat": (0, 165, 255),          # Vibrant Amber / Orange
    "dog": (255, 178, 50),         # Warm Sky Blue
    "bird": (255, 215, 0),         # Gold
    "chair": (200, 100, 255),      # Light Purple
    "couch": (200, 100, 255),
    "sofa": (200, 100, 255),
    "dining table": (180, 80, 220),
    "diningtable": (180, 80, 220),
    "potted plant": (50, 205, 50),
    "pottedplant": (50, 205, 50),
    "bottle": (255, 120, 0),       # Cyan-ish Blue
    "sports ball": (0, 255, 255),  # Yellow
    "default": (180, 180, 180),    # Neutral Slate Gray
}


def get_color_for_label(label: str) -> Tuple[int, int, int]:
    """Return BGR color tuple for a detected object label."""
    return LABEL_COLORS.get(label.lower(), LABEL_COLORS["default"])


def nms_boxes(
    boxes: List[Tuple[int, int, int, int]],
    scores: List[float],
    iou_threshold: float = 0.45,
    class_ids: Optional[List[int]] = None,
) -> List[int]:
    """
    Pure-Python / NumPy greedy Non-Maximum Suppression (NMS).
    Takes boxes in (x, y, w, h) format and scores, returns indices to keep.
    If class_ids is provided, suppression is performed per-class so that overlapping
    objects of different classes (e.g. person holding cat, cat on couch) are not suppressed.
    """
    if not boxes or not scores:
        return []

    # Sort candidate indices by confidence score descending
    idxs = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    keep: List[int] = []

    while idxs:
        current = idxs.pop(0)
        keep.append(current)

        cx1, cy1, cw, ch = boxes[current]
        cx2, cy2 = cx1 + cw, cy1 + ch
        current_area = max(0, cw) * max(0, ch)

        remaining: List[int] = []
        for i in idxs:
            # Per-class NMS: if class_ids provided, never suppress a different class
            if class_ids is not None and class_ids[i] != class_ids[current]:
                remaining.append(i)
                continue

            ix1, iy1, iw, ih = boxes[i]
            ix2, iy2 = ix1 + iw, iy1 + ih
            candidate_area = max(0, iw) * max(0, ih)

            # Intersection rectangle
            xx1 = max(cx1, ix1)
            yy1 = max(cy1, iy1)
            xx2 = min(cx2, ix2)
            yy2 = min(cy2, iy2)

            inter_w = max(0, xx2 - xx1)
            inter_h = max(0, yy2 - yy1)
            inter_area = inter_w * inter_h

            union_area = current_area + candidate_area - inter_area
            iou = (inter_area / float(union_area)) if union_area > 0 else 0.0

            if iou < iou_threshold:
                remaining.append(i)

        idxs = remaining

    return keep
