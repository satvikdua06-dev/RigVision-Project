"""EfficientNet-B0 binary PPE classifier — model loading and single-crop inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms


def load_classifier(model_dir: str | Path, device: torch.device) -> Tuple[nn.Module, dict]:
    """Load a trained EfficientNet-B0 PPE classifier.

    Returns (model, config_dict). The model is on `device` and in eval mode.
    """
    model_dir = Path(model_dir)
    with open(model_dir / "config.json") as f:
        config = json.load(f)

    m = models.efficientnet_b0(weights=None)
    in_features = m.classifier[1].in_features
    m.classifier = nn.Sequential(
        nn.Dropout(p=0.3, inplace=True),
        nn.Linear(in_features, 2),
    )
    m.load_state_dict(torch.load(model_dir / "best_model.pth", map_location=device))
    m.to(device).eval()
    return m, config


def build_transform(img_size: int = 224) -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])


def classify_crop(
    model: nn.Module,
    transform: transforms.Compose,
    crop_bgr: np.ndarray,
    device: torch.device,
) -> float:
    """Run EfficientNet-B0 on a BGR crop. Returns probability of class 1 (item present)."""
    if crop_bgr is None or crop_bgr.size == 0:
        return 0.0
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    x = transform(img).unsqueeze(0).to(device)
    with torch.no_grad():
        probs = torch.softmax(model(x), dim=1)[0]
    return probs[1].item()
