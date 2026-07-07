"""
Build caps_dataset from CelebA using the SAME crop as inference.

Instead of using raw CelebA images (face centered), we:
1. Run yolov8n-face on each CelebA image to get a face box
2. Apply the same PAD_TOP/PAD_BOTTOM/PAD_LEFT/PAD_RIGHT as inference
3. Save that padded crop as the training image

Training and inference see identical crops → no face-position artifact.

Run:
    python generate_caps_celeba.py

Output: ./caps_dataset  (replaces existing)
"""

import os
import shutil
import random
from pathlib import Path

import cv2
import numpy as np
from datasets import load_dataset
from huggingface_hub import hf_hub_download
from PIL import Image
from ultralytics import YOLO

# ── Config ───────────────────────────────────────────────────────────────────
OUTPUT_DIR    = "./caps_dataset"
MAX_POSITIVES = 2000
MAX_NEGATIVES = 2000
TRAIN_RATIO   = 0.80
SEED          = 42
IMG_EXT       = ".jpg"

# Must match video_test_classifier.py defaults
PAD_TOP    = 0.3   # reduced from 1.2 — enough to see cap crown, avoids false positives
PAD_BOTTOM = 0.1
PAD_LEFT   = 0.2
PAD_RIGHT  = 0.2

FACE_CONF  = 0.4   # lower threshold so we don't skip too many CelebA faces

random.seed(SEED)

# ── Load face model ───────────────────────────────────────────────────────────
print("Loading yolov8n-face...")
face_model_path = "yolov8n-face.pt"
if not os.path.exists(face_model_path):
    face_model_path = hf_hub_download(
        repo_id="ElenaRyumina/MASAI_models", filename="yolov8n-face.pt"
    )
face_model = YOLO(face_model_path)
face_model.to("cuda" if __import__("torch").cuda.is_available() else "cpu")
print("  face model ready")


def pil_to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def get_padded_crop(pil_img: Image.Image):
    """
    Detect largest face in image, apply inference-identical padding, return crop.
    Returns None if no face detected.
    """
    bgr = pil_to_bgr(pil_img)
    h, w = bgr.shape[:2]

    results = face_model.predict(source=bgr, conf=FACE_CONF, verbose=False)[0]
    if len(results.boxes) == 0:
        return None

    # Pick largest face (CelebA is face-centric, usually one face)
    areas = [(b.xyxy[0][2] - b.xyxy[0][0]) * (b.xyxy[0][3] - b.xyxy[0][1])
             for b in results.boxes]
    best  = results.boxes[int(np.argmax([a.cpu().item() for a in areas]))]
    fx1, fy1, fx2, fy2 = map(int, best.xyxy[0].cpu().tolist())

    fw, fh = fx2 - fx1, fy2 - fy1
    cx1 = max(0,  fx1 - int(fw * PAD_LEFT))
    cy1 = max(0,  fy1 - int(fh * PAD_TOP))
    cx2 = min(w,  fx2 + int(fw * PAD_RIGHT))
    cy2 = min(h,  fy2 + int(fh * PAD_BOTTOM))

    if (cx2 - cx1) <= 0 or (cy2 - cy1) <= 0:
        return None

    crop_bgr = bgr[cy1:cy2, cx1:cx2]
    crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(crop_rgb)


def save_crop(crop: Image.Image, out_img_path: Path, is_positive: bool):
    crop.convert("RGB").save(str(out_img_path))
    label_path = (
        out_img_path.parent.parent.parent
        / "labels"
        / out_img_path.parent.name
        / out_img_path.with_suffix(".txt").name
    )
    label_path.parent.mkdir(parents=True, exist_ok=True)
    with open(label_path, "w") as f:
        if is_positive:
            f.write("0 0.5 0.5 1.0 1.0\n")


# ── Load CelebA ───────────────────────────────────────────────────────────────
print("Loading CelebA...")
try:
    ds = load_dataset("flwrlabs/celeba", split="train")
    print(f"  {len(ds)} samples")
except Exception as e:
    print(f"  flwrlabs/celeba failed ({e}), trying celeba...")
    ds = load_dataset("celeba", split="train")
    print(f"  {len(ds)} samples")

print("Filtering by Wearing_Hat...")
pos_ds = ds.filter(lambda x: x["Wearing_Hat"] == 1)
neg_ds = ds.filter(lambda x: x["Wearing_Hat"] == 0)
print(f"  Positives: {len(pos_ds)}  Negatives: {len(neg_ds)}")

pos_idx = list(range(len(pos_ds))); random.shuffle(pos_idx); pos_idx = pos_idx[:MAX_POSITIVES * 2]
neg_idx = list(range(len(neg_ds))); random.shuffle(neg_idx); neg_idx = neg_idx[:MAX_NEGATIVES * 2]


# ── Generate crops ────────────────────────────────────────────────────────────
def collect_crops(dataset, indices, label, target_n):
    crops = []
    skipped = 0
    for i, idx in enumerate(indices):
        if len(crops) >= target_n:
            break
        sample = dataset[idx]
        crop = get_padded_crop(sample["image"])
        if crop is None:
            skipped += 1
            continue
        crops.append(crop)
        if (len(crops)) % 200 == 0:
            print(f"  [{label}] {len(crops)}/{target_n}  (skipped {skipped} no-face)")
    print(f"  [{label}] done: {len(crops)} crops, {skipped} skipped")
    return crops

print("\nGenerating positive crops (hat)...")
pos_crops = collect_crops(pos_ds, pos_idx, "pos", MAX_POSITIVES)

print("\nGenerating negative crops (no hat)...")
neg_crops = collect_crops(neg_ds, neg_idx, "neg", MAX_NEGATIVES)

# ── Split and save ────────────────────────────────────────────────────────────
def split(lst):
    n = int(len(lst) * TRAIN_RATIO)
    return lst[:n], lst[n:]

pos_train, pos_val = split(pos_crops)
neg_train, neg_val = split(neg_crops)

print(f"\nSplit — train: {len(pos_train)}+{len(neg_train)}  val: {len(pos_val)}+{len(neg_val)}")

if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)

for split_name, positives, negatives in [
    ("train", pos_train, neg_train),
    ("val",   pos_val,   neg_val),
]:
    img_dir = Path(OUTPUT_DIR) / "images" / split_name
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nWriting {split_name}...")
    for i, crop in enumerate(positives):
        save_crop(crop, img_dir / f"cap_{split_name}_{i:05d}{IMG_EXT}", is_positive=True)
    for i, crop in enumerate(negatives):
        save_crop(crop, img_dir / f"nocap_{split_name}_{i:05d}{IMG_EXT}", is_positive=False)
    print(f"  {len(positives) + len(negatives)} images written")

print(f"\nDone → {OUTPUT_DIR}")
print(f"PAD_TOP used: {PAD_TOP}  (set --pad-top {PAD_TOP} in video_test_classifier.py)")
print("Retrain:  python train_classifier.py --item cap")
