"""
Build glasses_dataset from CelebA (HuggingFace).

CelebA has ~200k aligned face images with 40 binary attributes.
We use the 'Eyeglasses' attribute: 1 = wearing glasses, 0 = not.

Run:
    pip install datasets pillow
    python generate_glasses_celeba.py

Output: ./glasses_dataset  (replaces the old fashionpedia-based one)
"""

import os
import shutil
import random
from pathlib import Path

from datasets import load_dataset
from PIL import Image

# ── Config ───────────────────────────────────────────────────────────────────
OUTPUT_DIR      = "./glasses_dataset"
MAX_POSITIVES   = 3000      # glasses-wearing images per split (train only; val is 20%)
MAX_NEGATIVES   = 3000      # no-glasses images per split
TRAIN_RATIO     = 0.80
SEED            = 42
IMG_EXT         = ".jpg"

random.seed(SEED)

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_eyeglasses(sample) -> bool:
    # flwrlabs/celeba exposes attributes as top-level keys
    return int(sample.get("Eyeglasses", 0)) > 0


def save_sample(sample, out_img_path: Path, is_positive: bool):
    img: Image.Image = sample["image"]
    img.convert("RGB").save(str(out_img_path))
    label_path = out_img_path.with_suffix(".txt")
    label_path = label_path.parent.parent.parent / "labels" / label_path.parent.name / label_path.name
    label_path.parent.mkdir(parents=True, exist_ok=True)
    with open(label_path, "w") as f:
        if is_positive:
            # Dummy full-image box (classifier ignores geometry; non-empty = positive)
            f.write("0 0.5 0.5 1.0 1.0\n")
        # empty file = negative


# ── Load ─────────────────────────────────────────────────────────────────────
print("Loading CelebA from HuggingFace (this may take a few minutes on first run)...")
try:
    ds = load_dataset("flwrlabs/celeba", split="train")
    print(f"Loaded flwrlabs/celeba — {len(ds)} samples")
except Exception as e:
    print(f"flwrlabs/celeba failed ({e}), trying official celeba...")
    ds = load_dataset("celeba", split="train")
    print(f"Loaded celeba — {len(ds)} samples")

# ── Split into positives / negatives ─────────────────────────────────────────
print("Filtering by Eyeglasses attribute (vectorized)...")
pos_ds = ds.filter(lambda x: x["Eyeglasses"] == 1)
neg_ds = ds.filter(lambda x: x["Eyeglasses"] == 0)
print(f"  Positives (glasses): {len(pos_ds)}")
print(f"  Negatives (no glasses): {len(neg_ds)}")

pos_indices = list(range(len(pos_ds)))
neg_indices = list(range(len(neg_ds)))
random.shuffle(pos_indices)
random.shuffle(neg_indices)
pos_indices = pos_indices[:MAX_POSITIVES]
neg_indices = neg_indices[:MAX_NEGATIVES]

def split(lst):
    n = int(len(lst) * TRAIN_RATIO)
    return lst[:n], lst[n:]

pos_train, pos_val = split(pos_indices)
neg_train, neg_val = split(neg_indices)

print(f"\nSplit:")
print(f"  Train — positives: {len(pos_train)}, negatives: {len(neg_train)}")
print(f"  Val   — positives: {len(pos_val)},  negatives: {len(neg_val)}")

# ── Write ─────────────────────────────────────────────────────────────────────
if os.path.exists(OUTPUT_DIR):
    print(f"\nRemoving old {OUTPUT_DIR}...")
    shutil.rmtree(OUTPUT_DIR)

for split_name, pos_indices, neg_indices in [
    ("train", pos_train, neg_train),
    ("val",   pos_val,   neg_val),
]:
    img_dir = Path(OUTPUT_DIR) / "images" / split_name
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nWriting {split_name}...")
    for idx, sample_idx in enumerate(pos_indices):
        sample = pos_ds[sample_idx]
        fname  = f"glasses_{split_name}_{idx:05d}{IMG_EXT}"
        save_sample(sample, img_dir / fname, is_positive=True)
        if (idx + 1) % 500 == 0:
            print(f"  positives: {idx+1}/{len(pos_indices)}")

    for idx, sample_idx in enumerate(neg_indices):
        sample = neg_ds[sample_idx]
        fname  = f"nogl_{split_name}_{idx:05d}{IMG_EXT}"
        save_sample(sample, img_dir / fname, is_positive=False)
        if (idx + 1) % 500 == 0:
            print(f"  negatives: {idx+1}/{len(neg_indices)}")

    total = len(pos_indices) + len(neg_indices)
    print(f"  {split_name}: {total} images written")

print(f"\nDone. Dataset saved to {OUTPUT_DIR}")
print("Now retrain with:  python train_classifier.py --item glasses")
