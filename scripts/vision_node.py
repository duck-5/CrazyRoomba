"""
Standalone Vision Node for Roomba (Raspberry Pi 5).
Reads from the camera, performs person detection, and POSTs to the controller.
Includes Resource Management: sleeps and frees camera/RAM when vision modes are off.
"""

import time
import requests
import logging
import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("vision_node")

API_STATUS_URL = "http://localhost:8000/api/perception/status"
API_PERCEPTION_URL = "http://localhost:8000/api/perception"
POLL_INTERVAL_SLEEP = 1.0  # seconds between status checks when inactive

class VisionNode:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.is_active = False
        self.cap = None
        self.net = None
        
        # We use a lightweight MobileNet-SSD for person detection via OpenCV DNN.
        self.prototxt_path = "MobileNetSSD_deploy.prototxt"
        self.model_path = "MobileNetSSD_deploy.caffemodel"
        
        # Class index 15 is 'person' in PASCAL VOC used by this MobileNet-SSD
        self.PERSON_CLASS_ID = 15
        self.CONFIDENCE_THRESHOLD = 0.5

    def _ensure_models_downloaded(self):
        """Automatically download the MobileNet-SSD model files if they are missing."""
        import os
        import urllib.request
        
        prototxt_url = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/voc/MobileNetSSD_deploy.prototxt"
        model_url = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/voc/MobileNetSSD_deploy.caffemodel"
        
        if not os.path.exists(self.prototxt_path):
            logger.info(f"Downloading {self.prototxt_path}...")
            urllib.request.urlretrieve(prototxt_url, self.prototxt_path)
            
        if not os.path.exists(self.model_path):
            logger.info(f"Downloading {self.model_path}... (This might take a minute)")
            urllib.request.urlretrieve(model_url, self.model_path)
            logger.info("Model download complete.")

    def wake_up(self):
        """Initialize camera and load ML models into RAM."""
        if self.is_active:
            return
        
        logger.info("Waking up Vision Node: Initializing camera and ML model...")
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        
        try:
            self._ensure_models_downloaded()
            self.net = cv2.dnn.readNetFromCaffe(self.prototxt_path, self.model_path)
            self.is_active = True
            logger.info("Vision Node is now ACTIVE.")
        except Exception as e:
            logger.error(f"Failed to load DNN model: {e}")
            self.sleep() # clean up

    def sleep(self):
        """Release camera and unload ML models to save Pi 5 resources."""
        if not self.is_active:
            return
            
        logger.info("Sleeping Vision Node: Releasing resources...")
        if self.cap:
            self.cap.release()
            self.cap = None
        self.net = None
        self.is_active = False
        logger.info("Vision Node is now ASLEEP.")

    def check_status(self) -> bool:
        """Poll the Roomba web API to see if a vision mode is active."""
        try:
            resp = requests.get(API_STATUS_URL, timeout=1.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("vision_active", False)
        except requests.exceptions.RequestException:
            pass
        return False

    def post_perception(self, x_center, bbox_width, confidence):
        """Send target data to the Roomba controller."""
        payload = {
            "target": {
                "target_person": {
                    "x_center": x_center,
                    "bbox_width": bbox_width,
                    "confidence": confidence
                }
            }
        }
        try:
            requests.post(API_PERCEPTION_URL, json=payload, timeout=0.1)
        except requests.exceptions.RequestException:
            pass

    def run(self):
        logger.info("Vision Node Started. Waiting for smart modes to activate...")
        while True:
            should_be_active = self.check_status()

            if should_be_active and not self.is_active:
                self.wake_up()
            elif not should_be_active and self.is_active:
                self.sleep()

            if not self.is_active:
                time.sleep(POLL_INTERVAL_SLEEP)
                continue

            # --- Active Vision Loop ---
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if not ret:
                    logger.warning("Failed to read frame")
                    time.sleep(0.1)
                    continue
                
                h, w = frame.shape[:2]
                blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
                self.net.setInput(blob)
                detections = self.net.forward()

                best_confidence = 0.0
                best_box = None

                for i in np.arange(0, detections.shape[2]):
                    confidence = detections[0, 0, i, 2]
                    class_idx = int(detections[0, 0, i, 1])

                    if class_idx == self.PERSON_CLASS_ID and confidence > self.CONFIDENCE_THRESHOLD:
                        if confidence > best_confidence:
                            best_confidence = confidence
                            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                            best_box = box

                if best_box is not None:
                    (startX, startY, endX, endY) = best_box.astype("int")
                    # Normalize bounding box for the controller
                    width_norm = (endX - startX) / w
                    x_center_norm = ((startX + endX) / 2.0) / w
                    
                    self.post_perception(x_center_norm, width_norm, float(best_confidence))
                else:
                    # Inform controller that target is lost
                    self.post_perception(0.5, 0.0, 0.0)
                    
            # Brief sleep to avoid pegging a CPU core at 100% and keep frame rate reasonable
            time.sleep(0.05)


if __name__ == "__main__":
    node = VisionNode(camera_index=0)
    try:
        node.run()
    except KeyboardInterrupt:
        logger.info("Shutting down vision node.")
        node.sleep()
