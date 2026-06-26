"""
RigVision-3D — ArUco Marker & Checkerboard Generator
======================================================

Generates printable calibration targets:
1. ArUco markers — for extrinsic calibration (camera position/rotation in room)
2. Checkerboard pattern — for intrinsic calibration (focal length, distortion)

USAGE:
    python generate_aruco.py --aruco          # Generate 6 ArUco markers
    python generate_aruco.py --checkerboard   # Generate checkerboard pattern
    python generate_aruco.py --both           # Generate both

WHAT TO DO WITH THEM:
    1. Print the checkerboard on A4 paper. Tape to a flat board.
    2. Print ArUco markers (ID 0-5). Tape to walls at KNOWN positions in the room.
       Measure their positions with a tape measure (in meters from origin).
    3. Run calibrate_intrinsic.py with the checkerboard.
    4. Run calibrate_extrinsic.py with the ArUco markers.
"""

from __future__ import annotations

import argparse
import os

import cv2
import numpy as np


def generate_aruco_markers(
    output_dir: str = ".",
    marker_ids: list[int] | None = None,
    marker_size: int = 200,
    dictionary_id: int = cv2.aruco.DICT_6X6_250,
) -> None:
    """Generate individual ArUco marker images.
    
    WHAT IS AN ArUco MARKER?
    ────────────────────────
    A square black-and-white pattern with a unique binary ID.
    OpenCV can detect these in images and determine their exact
    position and orientation relative to the camera.
    
    We place them at KNOWN positions in the room (measured with tape),
    so when the camera sees them, we can compute where the camera is.
    
    Args:
        output_dir: Where to save marker images.
        marker_ids: Which marker IDs to generate (default: 0-5).
        marker_size: Size of marker in pixels (for printing).
        dictionary_id: Which ArUco dictionary to use.
    """
    if marker_ids is None:
        marker_ids = list(range(6))
    
    dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
    
    os.makedirs(output_dir, exist_ok=True)
    
    for marker_id in marker_ids:
        # Generate marker image
        marker_img = cv2.aruco.generateImageMarker(dictionary, marker_id, marker_size)
        
        # Add white border for easier cutting
        border = 40
        bordered = cv2.copyMakeBorder(
            marker_img, border, border, border, border,
            cv2.BORDER_CONSTANT, value=255
        )
        
        # Add ID label below
        label = f"ArUco ID: {marker_id}"
        cv2.putText(bordered, label, (10, bordered.shape[0] - 10),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 2)
        
        filepath = os.path.join(output_dir, f"aruco_marker_{marker_id}.png")
        cv2.imwrite(filepath, bordered)
        print(f"  Saved {filepath}")
    
    print(f"\n✅ Generated {len(marker_ids)} ArUco markers in {output_dir}/")
    print("  Print these and tape them to walls at known positions.")
    print("  Measure each marker's center position (x, y, z) from the room origin.")


def generate_checkerboard(
    output_dir: str = ".",
    rows: int = 9,
    cols: int = 6,
    square_size_mm: int = 25,
) -> None:
    """Generate a checkerboard pattern for intrinsic calibration.
    
    WHAT IS INTRINSIC CALIBRATION?
    ──────────────────────────────
    Every camera has internal properties:
    - Focal length (fx, fy): how much the lens zooms
    - Principal point (cx, cy): where the optical axis hits the sensor
    - Distortion: barrel/pincushion warping from the lens
    
    These are encoded in the 3×3 intrinsic matrix K:
        K = [fx  0  cx]
            [ 0 fy  cy]
            [ 0  0   1]
    
    To find K, we take photos of a checkerboard from different angles.
    OpenCV finds the corners and computes K from the known geometry.
    
    Args:
        output_dir: Where to save the checkerboard image.
        rows: Number of inner corners vertically.
        cols: Number of inner corners horizontally.
        square_size_mm: Size of each square in mm (for printing).
    """
    # Create checkerboard image
    # Each square is square_size_mm pixels (prints at actual size on most printers)
    px_per_square = square_size_mm * 3  # 3px per mm for good print quality
    
    img_h = (rows + 1) * px_per_square
    img_w = (cols + 1) * px_per_square
    
    img = np.ones((img_h, img_w), dtype=np.uint8) * 255
    
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                y1 = r * px_per_square
                x1 = c * px_per_square
                img[y1:y1 + px_per_square, x1:x1 + px_per_square] = 0
    
    # Add border
    border = 50
    bordered = cv2.copyMakeBorder(
        img, border, border, border, border,
        cv2.BORDER_CONSTANT, value=255
    )
    
    # Add label
    label = f"Checkerboard {rows}x{cols}, square={square_size_mm}mm"
    cv2.putText(bordered, label, (10, bordered.shape[0] - 15),
                 cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
    
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "checkerboard.png")
    cv2.imwrite(filepath, bordered)
    
    print(f"  Saved {filepath}")
    print(f"\n✅ Generated {rows}×{cols} checkerboard (square = {square_size_mm}mm)")
    print("  Print on A4 paper and tape to a flat rigid board.")
    print(f"  When running calibrate_intrinsic.py, use --square_size {square_size_mm}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate calibration targets for RigVision-3D cameras"
    )
    parser.add_argument("--aruco", action="store_true", help="Generate ArUco markers")
    parser.add_argument("--checkerboard", action="store_true", help="Generate checkerboard")
    parser.add_argument("--both", action="store_true", help="Generate both")
    parser.add_argument("--output", default=".", help="Output directory")
    parser.add_argument("--marker-size", type=int, default=200, help="ArUco marker size in pixels")
    parser.add_argument("--rows", type=int, default=9, help="Checkerboard inner corner rows")
    parser.add_argument("--cols", type=int, default=6, help="Checkerboard inner corner columns")
    parser.add_argument("--square-size", type=int, default=25, help="Checkerboard square size in mm")
    
    args = parser.parse_args()
    
    if not (args.aruco or args.checkerboard or args.both):
        args.both = True  # Default to generating both
    
    if args.aruco or args.both:
        print("📐 Generating ArUco markers...")
        generate_aruco_markers(output_dir=args.output, marker_size=args.marker_size)
    
    if args.checkerboard or args.both:
        print("\n♟️ Generating checkerboard...")
        generate_checkerboard(
            output_dir=args.output,
            rows=args.rows, cols=args.cols,
            square_size_mm=args.square_size,
        )


if __name__ == "__main__":
    main()
