"""
RigVision-3D — YOLO Video Tester
==================================

Run YOLOv8 on a video file and see detections in real-time.
Draws bounding boxes, class labels, confidence scores, and
optionally saves the output video.

USAGE:
    python scripts/test_yolo_video.py path/to/video.mp4
    python scripts/test_yolo_video.py path/to/video.mp4 --save
    python scripts/test_yolo_video.py path/to/video.mp4 --model yolov8n.pt
    python scripts/test_yolo_video.py path/to/video.mp4 --conf 0.3

CONTROLS (while running):
    q     — quit
    SPACE — pause/resume
    s     — screenshot current frame
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
import numpy as np
from ultralytics import YOLO


# ── Colors for different classes ────────────────────────────
COLORS = {
    "person":   (0, 255, 100),   # green
    "hardhat":  (0, 220, 255),   # yellow
    "vest":     (255, 165, 0),   # orange
    "goggles":  (255, 0, 200),   # pink
    "default":  (200, 200, 200), # gray
}


def get_color(class_name: str) -> tuple:
    """Get BGR color for a class name."""
    name = class_name.lower()
    for key, color in COLORS.items():
        if key in name:
            return color
    return COLORS["default"]


def draw_detections(frame: np.ndarray, results, model) -> np.ndarray:
    """Draw bounding boxes, labels, and confidence on a frame."""
    annotated = frame.copy()

    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue

        for box in boxes:
            # Extract box data
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]
            color = get_color(cls_name)

            # Draw bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Draw label background
            label = f"{cls_name} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)

            # Draw label text
            cv2.putText(
                annotated, label, (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA
            )

    return annotated


def draw_stats(frame: np.ndarray, fps: float, frame_num: int,
               total_frames: int, detection_count: int) -> np.ndarray:
    """Draw stats overlay (FPS, frame count, detection count)."""
    h, w = frame.shape[:2]

    # Semi-transparent background
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (280, 95), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # Stats text
    cv2.putText(frame, f"FPS: {fps:.1f}", (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 100), 1, cv2.LINE_AA)
    cv2.putText(frame, f"Frame: {frame_num}/{total_frames}", (20, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(frame, f"Detections: {detection_count}", (20, 81),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 1, cv2.LINE_AA)

    return frame


def main():
    parser = argparse.ArgumentParser(
        description="Test YOLOv8 on a video file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Controls: q=quit, SPACE=pause, s=screenshot"
    )
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--model", default="yolov8l.pt",
                        help="YOLO model path (default: yolov8l.pt)")
    parser.add_argument("--conf", type=float, default=0.5,
                        help="Confidence threshold (default: 0.5)")
    parser.add_argument("--save", action="store_true",
                        help="Save output video with detections")
    parser.add_argument("--no-display", action="store_true",
                        help="Don't show preview window (use with --save)")
    args = parser.parse_args()

    # Validate video path
    if not os.path.exists(args.video):
        print(f"[ERROR] Video not found: {args.video}")
        sys.exit(1)

    # Load model
    print(f"[*] Loading model: {args.model}")
    model = YOLO(args.model)
    print(f"    Classes: {list(model.names.values())}")

    # Open video
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video: {args.video}")
        sys.exit(1)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_video = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"    Video: {w}x{h} @ {fps_video:.1f}fps, {total_frames} frames")
    print(f"    Confidence threshold: {args.conf}")
    print(f"    Controls: q=quit, SPACE=pause, s=screenshot\n")

    # Setup output video writer
    writer = None
    if args.save:
        out_path = os.path.splitext(args.video)[0] + "_yolo_output.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, fps_video, (w, h))
        print(f"    Saving output to: {out_path}\n")

    # Process frames
    frame_num = 0
    paused = False

    while cap.isOpened():
        if not paused:
            ret, frame = cap.read()
            if not ret:
                print(f"\n[OK] Finished processing {frame_num} frames")
                break

            frame_num += 1
            t_start = time.time()

            # Run YOLO
            results = model(frame, conf=args.conf, verbose=False)

            # Count detections
            det_count = sum(len(r.boxes) for r in results if r.boxes is not None)

            # Draw detections
            annotated = draw_detections(frame, results, model)

            # Calculate FPS
            elapsed = time.time() - t_start
            fps_actual = 1.0 / max(elapsed, 0.001)

            # Draw stats overlay
            annotated = draw_stats(annotated, fps_actual, frame_num, total_frames, det_count)

            # Save frame if requested
            if writer:
                writer.write(annotated)

            # Progress log
            if frame_num % 30 == 0:
                pct = frame_num / total_frames * 100
                print(f"  [{pct:5.1f}%] frame={frame_num}/{total_frames} "
                      f"detections={det_count} fps={fps_actual:.1f}")

        # Display
        if not args.no_display:
            cv2.imshow("RigVision - YOLO Test", annotated)

            key = cv2.waitKey(1 if not paused else 0) & 0xFF
            if key == ord('q'):
                print("\n[*] Quit by user")
                break
            elif key == ord(' '):
                paused = not paused
                print(f"  {'PAUSED' if paused else 'RESUMED'}")
            elif key == ord('s'):
                screenshot_path = f"screenshot_frame_{frame_num}.png"
                cv2.imwrite(screenshot_path, annotated)
                print(f"  Screenshot saved: {screenshot_path}")

    # Cleanup
    cap.release()
    if writer:
        writer.release()
        print(f"[OK] Output saved to: {out_path}")
    if not args.no_display:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
