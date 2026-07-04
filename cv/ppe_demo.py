"""
RigVision-3D — PPE Detection demo (standalone webcam).

Thin wrapper around cv/ppe_monitor.py: opens a webcam, feeds each frame to a PPEMonitor
(which handles person gating, on-head/on-eyes association, the 3-second debounce, proof
frames, and the Redis write), and shows a local preview window. The same engine runs
inside cv/pipeline.py, so behaviour is identical whether you demo standalone or folded
into the main pipeline.

All tunables come from .env (PPE_*). Run:  python cv/ppe_demo.py
"""

from __future__ import annotations

import os
import time

import cv2
import redis
import torch
from dotenv import load_dotenv

load_dotenv()

from ppe_monitor import PPEMonitor, MODEL_NAME, INFERENCE_IMGSZ, PPE_CONFIDENCE, \
    PERSON_CONFIDENCE, DETECT_SECONDS  # noqa: E402

CAMERA_INDEX   = int(os.getenv("PPE_CAMERA_INDEX", "0"))
PERSON_MODEL   = os.getenv("YOLO_MODEL", "yolov8l.pt")  # normal COCO model for persons
REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None


def detect_persons(person_model, frame):
    """COCO person boxes (class 0) above PERSON_CONFIDENCE, as (x1,y1,x2,y2)."""
    res = person_model.predict(source=frame, conf=PERSON_CONFIDENCE, classes=[0], verbose=False)[0]
    return [tuple(b.xyxy[0].tolist()) for b in res.boxes]


def main() -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[ppe] device={device}  ppe_model={MODEL_NAME}  person_model={PERSON_MODEL}  imgsz={INFERENCE_IMGSZ}")
    print(f"[ppe] conf={PPE_CONFIDENCE}  person_conf={PERSON_CONFIDENCE}  debounce={DETECT_SECONDS}s")

    from ultralytics import YOLO
    monitor = PPEMonitor(device=device)
    person_model = YOLO(PERSON_MODEL)
    if device:
        person_model.to(device)

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    r.ping()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise SystemExit(f"[ppe] could not open camera index {CAMERA_INDEX}")
    print("[ppe] running — press 'q' in the window to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ppe] frame grab failed")
                break

            person_boxes = detect_persons(person_model, frame)
            monitor.process(frame, r, person_boxes, now=time.time())
            monitor.annotate(frame)
            cv2.imshow("RigVision PPE Demo", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[ppe] stopped.")


if __name__ == "__main__":
    main()
