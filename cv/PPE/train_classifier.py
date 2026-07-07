"""
Binary PPE classifier using EfficientNet-B0.

Usage:
    python train_classifier.py --item cap
    python train_classifier.py --item glasses

Reads the existing YOLO-format datasets (caps_dataset / glasses_dataset).
A label file with at least one annotation = positive; empty file = negative.
Saves the best model to ./cap_classifier/ or ./glasses_classifier/.
"""

import argparse
import glob
import json
import os
import random

import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

# ── Reproducibility ──────────────────────────────────────────────────────────
torch.manual_seed(42)
random.seed(42)
torch.set_float32_matmul_precision("medium")

# ── Hyper-parameters ─────────────────────────────────────────────────────────
IMG_SIZE      = 224
BATCH_SIZE    = 16
NUM_WORKERS   = 4
MAX_EPOCHS    = 30
LR            = 3e-4
BACKBONE_LR   = 3e-5
WEIGHT_DECAY  = 1e-4
PATIENCE      = 6        # early-stop patience on val accuracy
DROPOUT       = 0.3

# ── Dataset ──────────────────────────────────────────────────────────────────
class PPEDataset(Dataset):
    """
    Reads YOLO-format image+label directories.
    Positive  = label file exists and has at least one annotation line.
    Negative  = label file is absent or empty.
    """
    def __init__(self, img_dir: str, label_dir: str, transform=None):
        self.transform  = transform
        self.img_paths  = sorted(
            glob.glob(os.path.join(img_dir, "*.jpg"))
            + glob.glob(os.path.join(img_dir, "*.jpeg"))
            + glob.glob(os.path.join(img_dir, "*.png"))
        )
        self.labels = []
        for p in self.img_paths:
            base      = os.path.splitext(os.path.basename(p))[0]
            lbl_path  = os.path.join(label_dir, f"{base}.txt")
            positive  = os.path.exists(lbl_path) and os.path.getsize(lbl_path) > 0
            self.labels.append(1 if positive else 0)

        pos = sum(self.labels)
        neg = len(self.labels) - pos
        print(f"  {img_dir}: {pos} positives, {neg} negatives ({len(self.labels)} total)")

    def __len__(self):
        return len(self.img_paths)

    def __getitem__(self, idx):
        img   = Image.open(self.img_paths[idx]).convert("RGB")
        label = self.labels[idx]
        if self.transform:
            img = self.transform(img)
        return img, label


# ── Model ─────────────────────────────────────────────────────────────────────
def build_model(dropout: float = DROPOUT) -> nn.Module:
    """EfficientNet-B0 with a replaced binary classification head."""
    weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
    model   = models.efficientnet_b0(weights=weights)
    in_features = model.classifier[1].in_features   # 1280
    model.classifier = nn.Sequential(
        nn.Dropout(p=dropout, inplace=True),
        nn.Linear(in_features, 2),
    )
    return model


# ── Transforms ───────────────────────────────────────────────────────────────
train_tf = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05),
    transforms.RandomRotation(10),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std =[0.229, 0.224, 0.225]),
])

val_tf = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std =[0.229, 0.224, 0.225]),
])


# ── Training loop ─────────────────────────────────────────────────────────────
def train(item: str):
    dataset_dir = f"./{item}_dataset" if item == "glasses" else f"./{item}s_dataset"
    output_dir  = f"./{item}_classifier"
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Training {item.upper()} classifier")
    print(f"Dataset : {dataset_dir}")
    print(f"Output  : {output_dir}")
    print(f"{'='*60}")

    # ── Datasets ──
    train_ds = PPEDataset(
        os.path.join(dataset_dir, "images/train"),
        os.path.join(dataset_dir, "labels/train"),
        transform=train_tf,
    )
    val_ds = PPEDataset(
        os.path.join(dataset_dir, "images/val"),
        os.path.join(dataset_dir, "labels/val"),
        transform=val_tf,
    )

    # Class-balanced sampler for imbalanced splits
    pos = sum(train_ds.labels)
    neg = len(train_ds.labels) - pos
    weights = [1.0 / neg if l == 0 else 1.0 / pos for l in train_ds.labels]
    sampler = torch.utils.data.WeightedRandomSampler(weights, len(weights))

    train_dl = DataLoader(
        train_ds, batch_size=BATCH_SIZE, sampler=sampler,
        num_workers=NUM_WORKERS, pin_memory=True, persistent_workers=NUM_WORKERS > 0,
    )
    val_dl = DataLoader(
        val_ds, batch_size=BATCH_SIZE, shuffle=False,
        num_workers=NUM_WORKERS, pin_memory=True, persistent_workers=NUM_WORKERS > 0,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device  : {device}")

    model = build_model().to(device)

    # Differential LRs: lower for the pretrained backbone, higher for new head
    backbone_params = [p for n, p in model.named_parameters()
                       if not n.startswith("classifier")]
    head_params     = [p for n, p in model.named_parameters()
                       if n.startswith("classifier")]
    optimizer = torch.optim.AdamW(
        [{"params": backbone_params, "lr": BACKBONE_LR},
         {"params": head_params,     "lr": LR}],
        weight_decay=WEIGHT_DECAY,
    )

    total_steps  = MAX_EPOCHS * len(train_dl)
    warmup_steps = int(0.05 * total_steps)
    def lr_lambda(step):
        if step < warmup_steps:
            return step / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return max(0.0, 0.5 * (1.0 + torch.cos(torch.tensor(progress * 3.14159)).item()))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    criterion = nn.CrossEntropyLoss()
    scaler    = torch.cuda.amp.GradScaler(enabled=(device.type == "cuda"))

    best_val_acc   = 0.0
    best_ckpt_path = os.path.join(output_dir, "best_model.pth")
    epochs_no_improve = 0

    for epoch in range(MAX_EPOCHS):
        # ── Train ──
        model.train()
        train_loss = 0.0
        for imgs, lbls in train_dl:
            imgs, lbls = imgs.to(device), lbls.to(device)
            optimizer.zero_grad()
            with torch.cuda.amp.autocast(enabled=(device.type == "cuda")):
                logits = model(imgs)
                loss   = criterion(logits, lbls)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            train_loss += loss.item()

        train_loss /= len(train_dl)

        # ── Validate ──
        model.eval()
        val_loss = 0.0
        correct  = 0
        total    = 0
        tp = fp = tn = fn = 0
        with torch.no_grad():
            for imgs, lbls in val_dl:
                imgs, lbls = imgs.to(device), lbls.to(device)
                with torch.cuda.amp.autocast(enabled=(device.type == "cuda")):
                    logits = model(imgs)
                    loss   = criterion(logits, lbls)
                val_loss += loss.item()
                preds = logits.argmax(dim=1)
                correct += (preds == lbls).sum().item()
                total   += lbls.size(0)
                tp += ((preds == 1) & (lbls == 1)).sum().item()
                fp += ((preds == 1) & (lbls == 0)).sum().item()
                tn += ((preds == 0) & (lbls == 0)).sum().item()
                fn += ((preds == 0) & (lbls == 1)).sum().item()

        val_loss /= len(val_dl)
        val_acc   = correct / total
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        improved = val_acc > best_val_acc
        marker   = " ✓" if improved else ""
        print(
            f"Epoch {epoch:02d}/{MAX_EPOCHS-1}  "
            f"train_loss={train_loss:.4f}  val_loss={val_loss:.4f}  "
            f"acc={val_acc:.4f}  prec={precision:.4f}  rec={recall:.4f}  F1={f1:.4f}"
            f"{marker}"
        )

        if improved:
            best_val_acc = val_acc
            torch.save(model.state_dict(), best_ckpt_path)
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= PATIENCE:
                print(f"Early stopping at epoch {epoch} (no improvement for {PATIENCE} epochs).")
                break

    # ── Export ──
    print(f"\nBest val accuracy: {best_val_acc:.4f}")
    print(f"Loading best checkpoint from {best_ckpt_path}...")
    model.load_state_dict(torch.load(best_ckpt_path, map_location=device))
    torch.save(model.state_dict(), best_ckpt_path)   # re-save to confirm

    config = {
        "item":        item,
        "architecture":"efficientnet_b0",
        "img_size":    IMG_SIZE,
        "threshold":   0.5,
        "class_names": ["absent", "present"],
        "val_accuracy": round(best_val_acc, 4),
        "mean": [0.485, 0.456, 0.406],
        "std":  [0.229, 0.224, 0.225],
    }
    with open(os.path.join(output_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print(f"Saved model  : {best_ckpt_path}")
    print(f"Saved config : {output_dir}/config.json")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--item", choices=["cap", "glasses"], required=True,
        help="Which PPE item to train a classifier for.",
    )
    args = parser.parse_args()
    train(args.item)
