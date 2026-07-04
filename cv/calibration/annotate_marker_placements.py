"""
RigVision-3D — AprilTag Placement Annotator
============================================

Draws recommended AprilTag placements onto a photo of the room (the master camera's
view), so you can see exactly where to physically tape each marker before running
world-pose calibration (see WORLD_POSE_GUIDE.md).

This is a DETERMINISTIC overlay — it draws on your real photo at exact pixel
positions. It does NOT use an image generator (those repaint the scene and move
things). The marker spots come from one of two sources:

  1. Built-in DEFAULTS below — my eyeballed positions for the sample living-room
     photo, given as fractions of width/height so they scale to any resolution.
     Tweak the fractions to match your own photo.

  2. A Gemini JSON file (the prompt in this chat asks Gemini to return pixel
     coords). Pass --gemini placements.json to use those instead.

USAGE
    pip install pillow
    python annotate_marker_placements.py --image room.jpg
    python annotate_marker_placements.py --image room.jpg --gemini placements.json
    python annotate_marker_placements.py --image room.jpg --out marked.png

PLACEMENT LOGIC (from WORLD_POSE_GUIDE.md)
    - 4 FLOOR tags spread to the corners + depth of the view (break clustering).
    - 2 WALL tags at ~1.5 m on differently-oriented walls (break coplanarity).
    - Avoid mirrors, the mandir, the cluttered sofa, and the leaning checkerboard.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont


# ── Default placements for the sample photo ─────────────────────────────────────
# (fx, fy) are fractions of image width/height (0..1), so they survive any resize.
# Tweak these to match your own photo, or override entirely via --gemini.
#   surface: "floor" (y=0) drawn green, "wall" (~1.5m) drawn cyan.
DEFAULT_MARKERS = [
    # id    surface    fx     fy     note
    ("F1", "floor",  0.32,  0.80, "front-left open tile, before the cabinet"),
    ("F2", "floor",  0.60,  0.86, "front-right open tile, before the sofa"),
    ("F3", "floor",  0.46,  0.70, "mid-floor centre (under the fan)"),
    ("F4", "floor",  0.44,  0.585, "far floor by the doorway threshold"),
    ("W1", "wall",   0.64,  0.46, "right wall above the sofa (left of mirror), ~1.5m"),
    ("W2", "wall",   0.585, 0.40, "back wall right of the doorway, ~1.5m"),
]

# Suggested world origin (a floor corner). Drawn as a small crosshair.
DEFAULT_ORIGIN = (0.30, 0.92, "world origin (0,0,0): pick this floor/tile corner")

COLOR_FLOOR = (70, 200, 120)     # green
COLOR_WALL  = (70, 180, 255)     # cyan
COLOR_ORIGIN = (255, 90, 80)     # red
COLOR_TEXT  = (255, 255, 255)
COLOR_SHADOW = (0, 0, 0)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_markers_from_gemini(path: str, W: int, H: int) -> Tuple[list, tuple]:
    """Parse the JSON shape produced by the Gemini prompt (pixel coords)."""
    with open(path) as f:
        data = json.load(f)
    markers = []
    for m in data.get("markers", []):
        cx, cy = m["image_pixel_center"]
        markers.append((m["id"], m.get("surface", "floor"),
                        cx / W, cy / H, m.get("reason", "")))
    origin = DEFAULT_ORIGIN
    wo = data.get("world_origin")
    if wo and "image_pixel" in wo:
        ox, oy = wo["image_pixel"]
        origin = (ox / W, oy / H, wo.get("description", "world origin"))
    return markers, origin


def annotate(image_path: str, markers: list, origin: tuple, out_path: str,
             draw_origin: bool = True) -> None:
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    r = max(14, int(min(W, H) * 0.018))   # marker radius scales with image
    f_label = _font(int(r * 1.4))
    f_note = _font(max(12, int(r * 0.8)))

    def text_with_shadow(xy, s, font, fill):
        x, y = xy
        draw.text((x + 1, y + 1), s, font=font, fill=COLOR_SHADOW)
        draw.text((x, y), s, font=font, fill=fill)

    # World origin crosshair (skip if the origin is already chosen / off-frame).
    if draw_origin and origin is not None:
        ox, oy, onote = origin
        px, py = int(ox * W), int(oy * H)
        s = r
        draw.line([(px - s, py), (px + s, py)], fill=COLOR_ORIGIN, width=3)
        draw.line([(px, py - s), (px, py + s)], fill=COLOR_ORIGIN, width=3)
        draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=COLOR_ORIGIN)
        text_with_shadow((px + s + 4, py - 6), "ORIGIN", f_note, COLOR_ORIGIN)

    # Markers.
    for mid, surface, fx, fy, note in markers:
        cx, cy = int(fx * W), int(fy * H)
        color = COLOR_WALL if surface == "wall" else COLOR_FLOOR
        # translucent disc + solid ring
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (70,))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)
        # id label centred
        tb = draw.textbbox((0, 0), mid, font=f_label)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        text_with_shadow((cx - tw / 2, cy - th / 2 - tb[1]), mid, f_label, COLOR_TEXT)
        # note below
        text_with_shadow((cx - r, cy + r + 4), note, f_note, color)

    # Legend.
    lx, ly = 16, 16
    box_h = 86 if (draw_origin and origin is not None) else 60
    draw.rectangle([lx - 8, ly - 8, lx + 360, ly + box_h], fill=(0, 0, 0, 140))
    draw.ellipse([lx, ly + 2, lx + 16, ly + 18], fill=COLOR_FLOOR)
    text_with_shadow((lx + 24, ly), "FLOOR tag (lay flat, y=0)", f_note, COLOR_TEXT)
    draw.ellipse([lx, ly + 28, lx + 16, ly + 44], fill=COLOR_WALL)
    text_with_shadow((lx + 24, ly + 26), "WALL tag (vertical, ~1.5 m)", f_note, COLOR_TEXT)
    if draw_origin and origin is not None:
        draw.line([(lx, ly + 60), (lx + 16, ly + 60)], fill=COLOR_ORIGIN, width=3)
        text_with_shadow((lx + 24, ly + 52), "World origin (0,0,0)", f_note, COLOR_TEXT)

    img.save(out_path)
    print(f"Saved annotated image -> {out_path}  ({W}x{H}, {len(markers)} markers)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Annotate AprilTag placements on a room photo")
    ap.add_argument("--image", required=True, help="Path to the camera-view photo")
    ap.add_argument("--gemini", default=None, help="Optional Gemini placements JSON")
    ap.add_argument("--out", default=None, help="Output path (default: <image>_marked.png)")
    ap.add_argument("--no-origin", action="store_true",
                    help="Don't draw the world origin (use if it's already set / off-frame)")
    args = ap.parse_args()

    if not os.path.exists(args.image):
        print(f"[ERROR] image not found: {args.image}")
        return

    out = args.out or os.path.splitext(args.image)[0] + "_marked.png"

    if args.gemini:
        with Image.open(args.image) as im:
            W, H = im.size
        markers, origin = _load_markers_from_gemini(args.gemini, W, H)
    else:
        markers, origin = DEFAULT_MARKERS, DEFAULT_ORIGIN

    annotate(args.image, markers, origin, out, draw_origin=not args.no_origin)


if __name__ == "__main__":
    main()
