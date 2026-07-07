"""
RigVision-3D — PPE monitor using EfficientNet-B0 binary classifiers.

Two-stage pipeline per person
──────────────────────────────
  1. yolov8n-face detects a face inside the person bounding-box crop.
  2. The face crop is padded (PAD_TOP=0.3 captures the cap crown above the face —
     this matches exactly how training images were generated in generate_caps_celeba.py).
  3. Both EfficientNet-B0 classifiers run on the padded crop in one pass:
       cap_classifier     → P(cap present)
       glasses_classifier → P(glasses present)
  4. Per-person rolling-average window smooths noisy per-frame scores before
     thresholding (default SCORE_WINDOW=15 frames ≈ 0.5s at 30fps).
  5. A 3-second debounce (ItemState) prevents status flips on transient occlusions.

Public API mirrors cv/ppe_monitor.py exactly — drop-in replacement.
All tunables live in .env (PPE_* prefix).
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from huggingface_hub import hf_hub_download
from ultralytics import YOLO

from .classifier import load_classifier, build_transform, classify_crop

# ── Config ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent

CAP_MODEL_DIR     = os.getenv("PPE_CAP_MODEL_DIR",
                               str(_HERE / "models" / "cap_classifier"))
GLASSES_MODEL_DIR = os.getenv("PPE_GLASSES_MODEL_DIR",
                               str(_HERE / "models" / "glasses_classifier"))

CAP_THRESHOLD     = float(os.getenv("PPE_CAP_THRESHOLD",     "0.97"))
GLASSES_THRESHOLD = float(os.getenv("PPE_GLASSES_THRESHOLD", "0.5"))
SCORE_WINDOW      = int(os.getenv("PPE_SCORE_WINDOW",        "90"))   # rolling-avg frames (~3s @ 30fps, matches video_test_classifier.py)

PERSON_CONFIDENCE = float(os.getenv("PPE_PERSON_CONFIDENCE", "0.3"))
DETECT_SECONDS    = float(os.getenv("PPE_DETECT_SECONDS",    "3.0"))

# Face detection crop — PAD_TOP=0.3 matches generate_caps_celeba.py training crops.
FACE_CONFIDENCE = float(os.getenv("PPE_FACE_CONFIDENCE",  "0.5"))
FACE_PAD_TOP    = float(os.getenv("PPE_FACE_PAD_TOP",    "0.3"))
FACE_PAD_BOTTOM = float(os.getenv("PPE_FACE_PAD_BOTTOM", "0.1"))
FACE_PAD_LEFT   = float(os.getenv("PPE_FACE_PAD_LEFT",   "0.2"))
FACE_PAD_RIGHT  = float(os.getenv("PPE_FACE_PAD_RIGHT",  "0.2"))
FACE_MODEL_PATH = os.getenv("PPE_FACE_MODEL_PATH", "")   # empty = HF auto-download

# Geometric head-crop fallback (used when face detector finds nothing).
HEAD_REGION  = float(os.getenv("PPE_HEAD_REGION",  "0.5"))
HEAD_PAD_X   = float(os.getenv("PPE_HEAD_PAD_X",   "0.2"))
HEAD_PAD_TOP = float(os.getenv("PPE_HEAD_PAD_TOP", "0.18"))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_proof_env = os.getenv("PPE_PROOF_DIR", "cv/ppe_proof")
PROOF_DIR  = (Path(_proof_env) if Path(_proof_env).is_absolute()
              else _REPO_ROOT / _proof_env)

PPE_KEY   = "rigvision:ppe:latest"
PROOF_KEY = "rigvision:ppe:proof:{item}"

ITEMS      = ("head_protection", "eye_protection")
ITEM_TOKEN = {"head_protection": "hat", "eye_protection": "glasses"}
NO_PERSON  = "no_person"
WORN       = "worn"
NOT_WORN   = "not_worn"

Box = Tuple[float, float, float, float]


def _to_person_status(confirmed: str) -> str:
    return confirmed if confirmed in ("detected", "missing") else "unknown"


# ── Debounce state machine (per item) ─────────────────────────────────────────
@dataclass
class ItemState:
    """Tracks one PPE item through a 3-second commit debounce."""
    confirmed: str = "unknown"
    since: float = field(default_factory=time.time)
    streak_value: Optional[str] = None
    streak_start: float = field(default_factory=time.time)
    proof: Optional[str] = None

    def update(self, raw: str, now: float) -> Optional[str]:
        """Feed per-frame raw condition. Returns newly committed status or None."""
        if raw == NO_PERSON:
            self.streak_value = None
            if self.confirmed != "no_person":
                self.confirmed = "no_person"
                self.since = now
            return None
        if raw != self.streak_value:
            self.streak_value = raw
            self.streak_start = now
            return None
        if now - self.streak_start < DETECT_SECONDS:
            return None
        target = "detected" if raw == WORN else "missing"
        if self.confirmed != target:
            self.confirmed = target
            self.since = now
            return target
        return None


def save_proof_frame(frame: np.ndarray, item: str, redis_client,
                     person_box: Optional[Box] = None) -> str:
    """Annotate + persist a 'missing PPE' evidence frame. Returns disk path."""
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    annotated = frame.copy()
    if person_box is not None:
        x1, y1, x2, y2 = (int(v) for v in person_box)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 220), 2)
    cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 40), (0, 0, 160), -1)
    cv2.putText(annotated, f"MISSING: {item}  @ {stamp}", (12, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    rel_path = f"{PROOF_DIR.as_posix()}/{item}_{ts}.jpg"
    cv2.imwrite(rel_path, annotated)
    ok, buf = cv2.imencode(".jpg", annotated)
    if ok and redis_client is not None:
        try:
            redis_client.set(PROOF_KEY.format(item=item),
                             base64.b64encode(buf.tobytes()).decode("ascii"))
        except Exception as e:
            print(f"[ppe] proof redis write failed: {e}")
    return rel_path


# ── Monitor ───────────────────────────────────────────────────────────────────
class PPEMonitor:
    """Stateful PPE judge using EfficientNet-B0 classifiers.

    Construct once; call `process_multi(...)` (pipeline) or `process(...)` (demo) per frame.
    """

    def __init__(self, device: Optional[str] = None, model: Optional[object] = None):
        import torch
        self._torch = torch
        self.device = (torch.device(device) if device
                       else torch.device("cuda" if torch.cuda.is_available() else "cpu"))

        # ── EfficientNet classifiers ──
        print(f"[ppe] Loading cap classifier  → {CAP_MODEL_DIR}")
        self.cap_model, cap_cfg = load_classifier(CAP_MODEL_DIR, self.device)
        self.cap_tf = build_transform(cap_cfg.get("img_size", 224))
        print(f"[ppe]   cap  val_accuracy={cap_cfg.get('val_accuracy', '?'):.4f}")

        print(f"[ppe] Loading glasses classifier → {GLASSES_MODEL_DIR}")
        self.glasses_model, gl_cfg = load_classifier(GLASSES_MODEL_DIR, self.device)
        self.glasses_tf = build_transform(gl_cfg.get("img_size", 224))
        print(f"[ppe]   glasses val_accuracy={gl_cfg.get('val_accuracy', '?'):.4f}")

        # ── yolov8n-face ──
        print("[ppe] Loading yolov8n-face...")
        try:
            if FACE_MODEL_PATH and os.path.exists(FACE_MODEL_PATH):
                face_path = FACE_MODEL_PATH
                print(f"[ppe]   using local: {FACE_MODEL_PATH}")
            else:
                face_path = hf_hub_download(
                    repo_id="ElenaRyumina/MASAI_models", filename="yolov8n-face.pt")
            self.face_model = YOLO(face_path)
        except Exception as e:
            print(f"[ppe] face model load failed ({e}), trying yolov8n-face.pt in cwd")
            self.face_model = YOLO("yolov8n-face.pt")
        self.face_model.to(self.device)

        print(f"[ppe] Ready on {self.device} | "
              f"cap_thr={CAP_THRESHOLD}  gl_thr={GLASSES_THRESHOLD}  "
              f"window={SCORE_WINDOW}f  debounce={DETECT_SECONDS}s")

        # Demo (single-person) state
        self.states: Dict[str, ItemState] = {item: ItemState() for item in ITEMS}
        self._prev_payload: Optional[str] = None
        self.last_boxes: Dict[str, List[Box]] = {"person": [], "head_crop": []}
        self._global_scores: Dict[str, deque] = {
            "cap":     deque(maxlen=SCORE_WINDOW),
            "glasses": deque(maxlen=SCORE_WINDOW),
        }

        # Multi-person (pipeline) state
        self.person_states: Dict[int, Dict[str, ItemState]] = {}
        self.person_scores: Dict[int, Dict[str, deque]] = {}
        self.last_person_status: Dict[int, Dict[str, str]] = {}

    # ── Crop helpers ──────────────────────────────────────────────────────────
    def _head_crop(self, frame: np.ndarray, box: Box) -> Tuple[np.ndarray, Box]:
        """Geometric head crop — fallback when face detector finds nothing."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        hx1 = max(0, int(x1 - HEAD_PAD_X * bw))
        hx2 = min(w, int(x2 + HEAD_PAD_X * bw))
        hy1 = max(0, int(y1 - HEAD_PAD_TOP * bh))
        hy2 = min(h, int(y1 + HEAD_REGION * bh))
        return frame[hy1:hy2, hx1:hx2], (hx1, hy1, hx2, hy2)

    def _face_crop(self, frame: np.ndarray, box: Box) -> Optional[Tuple[np.ndarray, Box]]:
        """Detect faces on the full frame (same as video_test_classifier.py), find the
        largest face whose centre falls within the person bounding box, pad to capture
        cap crown + glasses temples. Returns None when no face is found — callers must
        skip classification rather than falling back to an OOD geometric crop."""
        h, w = frame.shape[:2]
        px1, py1, px2, py2 = max(0, int(box[0])), max(0, int(box[1])), \
                              min(w, int(box[2])), min(h, int(box[3]))
        if px2 <= px1 or py2 <= py1:
            return None

        try:
            results = self.face_model.predict(
                source=frame, conf=FACE_CONFIDENCE, verbose=False)[0]
        except Exception as e:
            print(f"[ppe] face detection error: {e}")
            return None

        if results is None or results.boxes is None or len(results.boxes) == 0:
            return None

        # Keep only faces whose centre lies within this person's bounding box.
        candidates = []
        for b in results.boxes:
            fx1, fy1, fx2, fy2 = map(int, b.xyxy[0].cpu().tolist())
            cx, cy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
            if px1 <= cx <= px2 and py1 <= cy <= py2:
                area = (fx2 - fx1) * (fy2 - fy1)
                candidates.append((area, fx1, fy1, fx2, fy2))

        if not candidates:
            return None

        # Largest matching face.
        _, fx1, fy1, fx2, fy2 = max(candidates, key=lambda c: c[0])
        fw, fh = fx2 - fx1, fy2 - fy1

        cx1 = max(0, fx1 - int(fw * FACE_PAD_LEFT))
        cy1 = max(0, fy1 - int(fh * FACE_PAD_TOP))    # 0.3 × face height above
        cx2 = min(w, fx2 + int(fw * FACE_PAD_RIGHT))
        cy2 = min(h, fy2 + int(fh * FACE_PAD_BOTTOM))

        if cx2 <= cx1 or cy2 <= cy1:
            return None
        return frame[cy1:cy2, cx1:cx2], (cx1, cy1, cx2, cy2)

    # ── Classification ────────────────────────────────────────────────────────
    def _classify(self, crop: np.ndarray) -> Tuple[float, float]:
        """Run both EfficientNet classifiers on one BGR crop.
        Returns (cap_prob, glasses_prob)."""
        cap_p  = classify_crop(self.cap_model,     self.cap_tf,     crop, self.device)
        gl_p   = classify_crop(self.glasses_model, self.glasses_tf, crop, self.device)
        return cap_p, gl_p

    def _detect_with_buffers(
        self,
        frame: np.ndarray,
        box: Box,
        cap_buf: deque,
        glasses_buf: deque,
    ) -> Tuple[Optional[bool], Optional[bool], Optional[Box]]:
        """Get face crop, classify, update rolling-average buffers, threshold.
        Returns (cap_present, glasses_present, crop_box).
        All three are None when no face was detected — callers must treat None as
        'no data' and NOT feed it into WORN/NOT_WORN logic."""
        result = self._face_crop(frame, box)
        if result is None:
            return None, None, None
        crop, crop_box = result
        cap_p, gl_p = self._classify(crop)
        cap_buf.append(cap_p)
        glasses_buf.append(gl_p)
        cap_avg = sum(cap_buf) / len(cap_buf)
        gl_avg  = sum(glasses_buf) / len(glasses_buf)
        return cap_avg >= CAP_THRESHOLD, gl_avg >= GLASSES_THRESHOLD, crop_box

    # ── Pipeline path: multi-person, multi-camera ────────────────────────────
    def process_multi(
        self,
        frames_by_cam: Dict[int, np.ndarray],
        persons_cam_boxes: Dict[int, Dict[int, Box]],
        redis_client,
        now: Optional[float] = None,
    ) -> Dict[int, Dict[str, str]]:
        """Judge PPE per person across all provided feeds.

        frames_by_cam     — {cam_id: frame}
        persons_cam_boxes — {person_id: {cam_id: box}}

        A person is WORN if the item is detected on ANY feed (OR logic). Returns
        and updates `last_person_status`."""
        now = now or time.time()
        out: Dict[int, Dict[str, str]] = {}

        for pid, cam_boxes in persons_cam_boxes.items():
            ps = self.person_states.setdefault(
                pid, {item: ItemState() for item in ITEMS})
            psc = self.person_scores.setdefault(pid, {
                "cap":     deque(maxlen=SCORE_WINDOW),
                "glasses": deque(maxlen=SCORE_WINDOW),
            })

            cap_any = glasses_any = False
            face_seen = False
            for cam_id, box in cam_boxes.items():
                frame = frames_by_cam.get(cam_id)
                if frame is None:
                    continue
                cap_present, gl_present, _ = self._detect_with_buffers(
                    frame, box, psc["cap"], psc["glasses"])
                if cap_present is None:
                    continue  # no face detected on this feed — skip, don't count as NOT_WORN
                face_seen = True
                cap_any     = cap_any or cap_present
                glasses_any = glasses_any or gl_present

            if not face_seen:
                # No face detected on any camera this tick — skip debounce update entirely
                # so confirmed state doesn't drift from stale NOT_WORN signals.
                out[pid] = {
                    ITEM_TOKEN[item]: _to_person_status(ps[item].confirmed)
                    for item in ITEMS
                }
                continue

            raw = {
                "head_protection": WORN if cap_any     else NOT_WORN,
                "eye_protection":  WORN if glasses_any else NOT_WORN,
            }
            for item in ITEMS:
                transition = ps[item].update(raw[item], now)
                if transition == "missing":
                    cam_id, box = next(iter(cam_boxes.items()))
                    ps[item].proof = save_proof_frame(
                        frames_by_cam[cam_id],
                        f"{pid}_{ITEM_TOKEN[item]}",
                        redis_client,
                        person_box=box,
                    )
                elif transition == "detected":
                    ps[item].proof = None
            out[pid] = {
                ITEM_TOKEN[item]: _to_person_status(ps[item].confirmed)
                for item in ITEMS
            }

        # Prune state for people who have left the frame.
        for gone in [pid for pid in self.person_states if pid not in persons_cam_boxes]:
            self.person_states.pop(gone, None)
            self.person_scores.pop(gone, None)

        self.last_person_status = out
        return out

    # ── Demo path: single-person, single frame ───────────────────────────────
    def process(
        self,
        frame: np.ndarray,
        redis_client,
        person_boxes: List[Box],
        now: Optional[float] = None,
    ) -> dict:
        """Run one PPE detection step for a list of person boxes; write Redis.
        `person_boxes` are full-body (x1,y1,x2,y2) in pixel space of `frame`."""
        now = now or time.time()
        persons = list(person_boxes or [])
        head_crops: List[Box] = []

        cap_any = glasses_any = False
        face_seen = False
        for box in persons:
            cap_p, gl_p, crop_box = self._detect_with_buffers(
                frame, box,
                self._global_scores["cap"],
                self._global_scores["glasses"],
            )
            if crop_box is not None:
                head_crops.append(crop_box)
            if cap_p is None:
                continue  # no face found — skip, don't count as NOT_WORN
            face_seen = True
            cap_any     = cap_any or cap_p
            glasses_any = glasses_any or gl_p

        self.last_boxes = {"person": persons, "head_crop": head_crops}

        person_present = len(persons) > 0
        if not person_present:
            raw = {"head_protection": NO_PERSON, "eye_protection": NO_PERSON}
        elif not face_seen:
            raw = None  # persons present but no face detected — don't update debounce
        else:
            raw = {
                "head_protection": WORN if cap_any     else NOT_WORN,
                "eye_protection":  WORN if glasses_any else NOT_WORN,
            }

        if raw is not None:
            for item in ITEMS:
                transition = self.states[item].update(raw[item], now)
                if transition == "missing":
                    self.states[item].proof = save_proof_frame(frame, item, redis_client)
                elif transition == "detected":
                    self.states[item].proof = None

        payload = {
            "person_present": person_present,
            **{
                item: {
                    "status": self.states[item].confirmed,
                    "since":  round(self.states[item].since, 2),
                    "proof":  self.states[item].proof,
                }
                for item in ITEMS
            },
        }
        serialized = json.dumps(payload, sort_keys=True)
        if serialized != self._prev_payload and redis_client is not None:
            self._prev_payload = serialized
            try:
                redis_client.set(PPE_KEY, json.dumps(payload))
            except Exception as e:
                print(f"[ppe] redis write failed: {e}")
        return payload

    # ── Annotation ────────────────────────────────────────────────────────────
    def annotate(self, frame: np.ndarray) -> None:
        """Draw latest person/crop boxes and per-item status onto `frame` in-place."""
        for (x1, y1, x2, y2) in self.last_boxes.get("person", []):
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (90, 90, 90), 1)
        for (x1, y1, x2, y2) in self.last_boxes.get("head_crop", []):
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)
        colors = {
            "detected":  (0, 200, 0),
            "missing":   (0, 0, 220),
            "no_person": (150, 150, 150),
            "unknown":   (180, 180, 180),
        }
        for i, item in enumerate(ITEMS):
            s = self.states[item]
            cv2.putText(
                frame,
                f"{item}: {s.confirmed.upper()}",
                (12, 30 + i * 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                colors.get(s.confirmed, (200, 200, 200)),
                2, cv2.LINE_AA,
            )
