"""
RigVision-3D — Multi-Camera Recording Script
==============================================

Records synchronized video from multiple cameras for offline testing.

USAGE:
    python record_test_video.py --cameras 0 1 2 --duration 60 --output test_videos/
    python record_test_video.py --cameras rtsp://192.168.1.101:4747/video --duration 30

The recorded videos can be played back through the pipeline:
    cd cv && python pipeline.py --mode video --cameras ../test_videos/cam_0.mp4
"""

from __future__ import annotations

import argparse
import os
import time

import cv2


def record(
    camera_sources: list[str],
    duration: int,
    output_dir: str,
    fps: float = 30.0,
) -> None:
    """Record from multiple cameras simultaneously.
    
    Args:
        camera_sources: List of camera indices or RTSP URLs.
        duration: Recording duration in seconds.
        output_dir: Directory to save videos.
        fps: Frames per second for output video.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Open cameras
    caps = {}
    writers = {}
    
    for i, source in enumerate(camera_sources):
        try:
            cam_idx = int(source)
            cap = cv2.VideoCapture(cam_idx)
        except ValueError:
            cap = cv2.VideoCapture(source)
        
        if not cap.isOpened():
            print(f"❌ Cannot open camera: {source}")
            continue
        
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        output_path = os.path.join(output_dir, f"cam_{i}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
        
        caps[i] = cap
        writers[i] = writer
        print(f"  📷 Camera {i}: {source} ({w}×{h}) → {output_path}")
    
    if not caps:
        print("❌ No cameras opened!")
        return
    
    print(f"\n🔴 Recording for {duration}s... Press Ctrl+C to stop early.\n")
    
    start_time = time.time()
    frame_count = 0
    
    try:
        while time.time() - start_time < duration:
            for cam_id, cap in caps.items():
                ret, frame = cap.read()
                if ret:
                    writers[cam_id].write(frame)
            
            frame_count += 1
            if frame_count % int(fps * 5) == 0:
                elapsed = time.time() - start_time
                print(f"  {elapsed:.0f}s / {duration}s ({frame_count} frames)")
    except KeyboardInterrupt:
        print("\n  Stopped early.")
    
    # Cleanup
    for cap in caps.values():
        cap.release()
    for writer in writers.values():
        writer.release()
    
    elapsed = time.time() - start_time
    print(f"\n✅ Recorded {frame_count} frames ({elapsed:.1f}s) to {output_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record multi-camera test videos")
    parser.add_argument("--cameras", nargs="+", required=True, help="Camera sources")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    parser.add_argument("--output", default="test_videos", help="Output directory")
    parser.add_argument("--fps", type=float, default=30.0, help="Output FPS")
    
    args = parser.parse_args()
    record(args.cameras, args.duration, args.output, args.fps)


if __name__ == "__main__":
    main()
