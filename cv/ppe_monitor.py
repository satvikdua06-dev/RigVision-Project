"""
RigVision-3D — PPE monitor (shared engine).

Encapsulates everything needed to judge PPE compliance from a single video frame so the
same logic runs in two places without duplication:

  • cv/ppe_demo.py     — standalone webcam demo (its own preview window).
  • cv/pipeline.py     — folded into the main CV loop, sharing the pipeline's camera.

For two logical items — `body_gear` (backpack — a large, distance-friendly stand-in that
detects far more reliably at 4–5 m than glasses) and `head_protection` (hat variants /
helmet) — it reports whether the item is being WORN, applying:

  1. Person gating — nothing is judged unless a person is in frame (no person =>
     "no_person", no proof frame; never flags an empty room).
  2. Spatial association — a backpack counts only if its box is centred inside the
     person's box; a hat only if it sits on the top of the head/face anchor. Objects
     elsewhere in the frame are rejected (bbox-geometry only).
  3. 3-second debounce — a status flips to detected/missing only after the raw condition
     holds continuously for PPE_DETECT_SECONDS. The WORN->NOT_WORN commit saves an
     annotated proof frame to disk + Redis.

Output is published to Redis on the `rigvision:ppe:latest` seam. All tunables come from
.env (PPE_*), so there is one place to change them.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# ── Config (single source: .env) ────────────────────────────────────────────────
MODEL_NAME        = os.getenv("PPE_MODEL", "yolov8x-oiv7.pt")
INFERENCE_IMGSZ   = int(os.getenv("PPE_INFERENCE_IMGSZ", "1280"))
PPE_CONFIDENCE    = float(os.getenv("PPE_CONFIDENCE", "0.1"))
PERSON_CONFIDENCE = float(os.getenv("PPE_PERSON_CONFIDENCE", "0.3"))
DETECT_SECONDS    = float(os.getenv("PPE_DETECT_SECONDS", "3.0"))
# Resolve the proof dir against the repo root (parent of cv/) so it lands in the same
# place regardless of the caller's cwd — the pipeline runs from cv/, scripts from root.
_REPO_ROOT        = Path(__file__).resolve().parent.parent
_proof_env        = os.getenv("PPE_PROOF_DIR", "cv/ppe_proof")
PROOF_DIR         = Path(_proof_env) if Path(_proof_env).is_absolute() else _REPO_ROOT / _proof_env

PPE_KEY   = "rigvision:ppe:latest"
PROOF_KEY = "rigvision:ppe:proof:{item}"   # base64 JPEG per item, for the backend

# ── PPE class → logical item mapping ────────────────────────────────────────────
# Body-gear item: a large, distance-friendly object (backpack) replaces glasses, which
# are too small to detect reliably at 4–5 m. Worn/carried on the body.
BODY_CLASSES = {"Backpack"}
HEAD_CLASSES = {"Hat", "Sun hat", "Cowboy hat", "Fedora", "Sombrero", "Helmet"}  # head_protection items
# Anatomy anchors (from the same OIV7 model) used to localise where the head is, so the
# hat association is framing-independent (works whether the person is standing or reclined).
FACE_CLASS   = "Human face"
HEAD_ANCHOR_CLASS = "Human head"
PERSON_CLASS = "Person"

ITEMS = ("body_gear", "head_protection")

# Raw per-frame condition for an item.
NO_PERSON = "no_person"
WORN      = "worn"
NOT_WORN  = "not_worn"

Box = Tuple[float, float, float, float]


# ── Spatial association ─────────────────────────────────────────────────────────
def _center(box: Box) -> Tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _boxes_overlap(a: Box, b: Box) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def _point_in_box(pt: Tuple[float, float], box: Box) -> bool:
    x, y = pt
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def _overlaps_any(box: Box, others: List[Box]) -> bool:
    return any(_boxes_overlap(box, o) for o in others)


# ── Primary association ────────────────────────────────────────────────────────
def body_worn(body_boxes: List[Box], person_boxes: List[Box]) -> bool:
    """Body gear (backpack) is WORN/CARRIED if a backpack box is centred inside a person
    box. A backpack sitting on the floor (not over a person) is rejected."""
    for b in body_boxes:
        bc = _center(b)
        if any(_point_in_box(bc, p) for p in person_boxes):
            return True
    return False


def head_worn(hat_boxes: List[Box], head_boxes: List[Box], face_boxes: List[Box],
              person_boxes: List[Box]) -> bool:
    """A hat/helmet is WORN if it overlaps the top of a head (or face) anchor belonging to
    a person. A hat held at chest/waist doesn't overlap the head anchor and is rejected.
    Falls back to the person-box band when no head/face anchor was detected."""
    anchors = [a for a in (head_boxes or face_boxes) if _overlaps_any(a, person_boxes)]
    for h in hat_boxes:
        _, hcy = _center(h)
        for (ax1, ay1, ax2, ay2) in anchors:
            ah = ay2 - ay1
            # hat overlaps the anchor and sits on/above its upper half (the crown)
            if _boxes_overlap(h, (ax1, ay1, ax2, ay2)) and hcy < ay1 + 0.5 * ah:
                return True
    if not anchors:
        return any(_worn_on_head_band(h, p) for h in hat_boxes for p in person_boxes)
    return False


# ── Per-person association: restrict gear/hat/anchors to ONE person's box ──────────
def person_body_worn(person: Box, body_boxes: List[Box]) -> bool:
    """True if THIS person is wearing/carrying a backpack: a backpack box centred inside
    this person's box. Another person's backpack is excluded by the containment check."""
    return any(_point_in_box(_center(b), person) for b in body_boxes)


def person_hat_worn(person: Box, hat_boxes: List[Box], head_boxes: List[Box],
                    face_boxes: List[Box]) -> bool:
    """True if THIS person is wearing a hat/helmet sitting on the top of their head/face."""
    hats_in = [h for h in hat_boxes if _boxes_overlap(h, person)]
    anchors = [a for a in (head_boxes or face_boxes) if _boxes_overlap(a, person)]
    for h in hats_in:
        _, hcy = _center(h)
        for (ax1, ay1, ax2, ay2) in anchors:
            ah = ay2 - ay1
            if _boxes_overlap(h, (ax1, ay1, ax2, ay2)) and hcy < ay1 + 0.5 * ah:
                return True
    if not anchors:
        return any(_worn_on_head_band(h, person) for h in hats_in)
    return False


# Maps the debounce's confirmed state → the compact per-person status the frontend reads.
ITEM_TOKEN = {"body_gear": "backpack", "head_protection": "hat"}


def _to_person_status(confirmed: str) -> str:
    """detected → detected, missing → missing, anything else → unknown."""
    return confirmed if confirmed in ("detected", "missing") else "unknown"


# ── Fallback heuristics: person-box bands (used only when no face/head anchor) ─────
def _worn_on_head_band(hat_box: Box, person_box: Box) -> bool:
    px1, py1, px2, py2 = person_box
    H = py2 - py1
    head_band = (px1, py1 - 0.05 * H, px2, py1 + 0.20 * H)
    _, hcy = _center(hat_box)
    return _boxes_overlap(hat_box, head_band) and hcy < py1 + 0.18 * H


# ── Debounce state machine (per item) ───────────────────────────────────────────
@dataclass
class ItemState:
    """Tracks one PPE item through the 3-second commit debounce."""
    confirmed: str = "unknown"          # what the frontend shows: detected/missing/no_person/unknown
    since: float = field(default_factory=time.time)
    streak_value: Optional[str] = None  # raw condition currently being held
    streak_start: float = field(default_factory=time.time)
    proof: Optional[str] = None         # disk path of the latest "missing" proof frame

    def update(self, raw: str, now: float) -> Optional[str]:
        """Feed the per-frame raw condition. Returns the NEW confirmed status if it just
        committed a transition (else None)."""
        # No person: pause judging, surface "no_person", and reset the streak so a
        # returning person is evaluated fresh.
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
    """Annotate + persist a 'missing' proof frame. Returns the relative disk path.

    Writes a disk copy (permanent evidence) and a base64 JPEG to Redis (so the backend
    can serve it without filesystem access). If `person_box` is given, the offending
    person is outlined so the evidence points at exactly who was non-compliant."""
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


# ── Monitor ──────────────────────────────────────────────────────────────────────
class PPEMonitor:
    """Stateful PPE judge. Construct once, call `process(frame, redis_client)` per frame
    (or every Nth frame — the debounce uses wall-clock time, so throttling is fine)."""

    def __init__(self, device: Optional[str] = None, model: Optional[object] = None):
        from ultralytics import YOLO
        self.model = model or YOLO(MODEL_NAME)
        if device:
            try:
                self.model.to(device)
            except Exception as e:
                print(f"[ppe] could not move model to {device}: {e}")

        # The OIV7 model supplies PPE items (backpack/hat) plus face/head anchors used to
        # localise the crown. Person detection is the caller's job — the pipeline's
        # reliable COCO detector — passed into process(). OIV7's own "Person" class is
        # skipped because it misfires on close-up framing.
        name_to_id = {name: i for i, name in self.model.names.items()}
        wanted = BODY_CLASSES | HEAD_CLASSES | {FACE_CLASS, HEAD_ANCHOR_CLASS}
        self.class_ids = [name_to_id[n] for n in wanted if n in name_to_id]
        missing = [n for n in wanted if n not in name_to_id]
        if missing:
            print(f"[ppe] WARNING: PPE classes not in this model: {missing}")

        self.states: Dict[str, ItemState] = {item: ItemState() for item in ITEMS}
        self._prev_payload: Optional[str] = None
        self.last_boxes: Dict[str, List[Box]] = {"person": [], "body": [], "head": []}

        # Per-person debounce state, keyed by the caller's stable person id.
        self.person_states: Dict[int, Dict[str, ItemState]] = {}
        # Latest debounced status per person id, e.g. {100001: {"backpack": "detected",
        # "hat": "missing"}}. The pipeline reads this each frame to stamp onto persons.
        self.last_person_status: Dict[int, Dict[str, str]] = {}

    def _detect(self, frame: np.ndarray):
        """One OIV7 pass → (body, hat, face, head_anchor) box lists in frame pixel space."""
        result = self.model.predict(
            source=frame, conf=PPE_CONFIDENCE, classes=self.class_ids,
            imgsz=INFERENCE_IMGSZ, verbose=False,
        )[0]
        body, hat, face, head = [], [], [], []
        for box in result.boxes:
            name = result.names.get(int(box.cls[0].item()), "")
            xyxy = tuple(box.xyxy[0].tolist())
            if name in BODY_CLASSES:
                body.append(xyxy)
            elif name in HEAD_CLASSES:
                hat.append(xyxy)
            elif name == FACE_CLASS:
                face.append(xyxy)
            elif name == HEAD_ANCHOR_CLASS:
                head.append(xyxy)
        return body, hat, face, head

    def _detect_in_crop(self, frame: np.ndarray, box: Box,
                        pad: float = 0.15) -> Tuple[bool, bool]:
        """Run detection on a padded crop around ONE person, so the model sees them
        enlarged (the person fills the 1280px input instead of being a few hundred px in
        the whole frame). This is the key to detecting worn items at 4–5 m.

        Because the crop is essentially just this person, a detected backpack/hat is
        attributed to them by presence — returns (body_present, hat_present)."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        bw, bh = (x2 - x1), (y2 - y1)
        cx1 = max(0, int(x1 - pad * bw)); cy1 = max(0, int(y1 - pad * bh))
        cx2 = min(w, int(x2 + pad * bw)); cy2 = min(h, int(y2 + pad * bh))
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return False, False
        res = self.model.predict(
            source=crop, conf=PPE_CONFIDENCE, classes=self.class_ids,
            imgsz=INFERENCE_IMGSZ, verbose=False,
        )[0]
        body_present = hat_present = False
        for b in res.boxes:
            name = res.names.get(int(b.cls[0].item()), "")
            if name in BODY_CLASSES:
                body_present = True
            elif name in HEAD_CLASSES:
                hat_present = True
        return body_present, hat_present

    def process_multi(self, frames_by_cam: Dict[int, np.ndarray],
                      persons_cam_boxes: Dict[int, Dict[int, Box]],
                      redis_client, now: Optional[float] = None) -> Dict[int, Dict[str, str]]:
        """Judge PPE per person across ALL provided feeds.

        `frames_by_cam`     — {cam_id: frame} for every camera PPE runs on.
        `persons_cam_boxes` — {person_id: {cam_id: box}} — each person's box on each
                              camera that sees them (same pixel space as that cam's frame).

        Detection runs on a per-person CROP (zoomed in, so worn items are large enough to
        detect at 4–5 m). A person's item counts as WORN if it is worn on ANY feed (so as
        long as one of the two cameras sees the backpack/hat, it shows). Each person keeps
        an independent 3-second debounce; missing transitions save a proof frame keyed
        `{id}_{backpack|hat}`. Updates and returns `last_person_status`."""
        now = now or time.time()

        out: Dict[int, Dict[str, str]] = {}
        for pid, cam_boxes in persons_cam_boxes.items():
            ps = self.person_states.setdefault(pid, {item: ItemState() for item in ITEMS})
            # OR across every feed that sees this person, detecting on a zoomed crop.
            body_any = hat_any = False
            for cam_id, box in cam_boxes.items():
                frame = frames_by_cam.get(cam_id)
                if frame is None:
                    continue
                body_present, hat_present = self._detect_in_crop(frame, box)
                body_any = body_any or body_present
                hat_any = hat_any or hat_present
            raw = {"body_gear": WORN if body_any else NOT_WORN,
                   "head_protection": WORN if hat_any else NOT_WORN}

            for item in ITEMS:
                transition = ps[item].update(raw[item], now)
                if transition == "missing":
                    # Use any feed that sees the person for the evidence frame.
                    cam_id, box = next(iter(cam_boxes.items()))
                    ps[item].proof = save_proof_frame(
                        frames_by_cam[cam_id], f"{pid}_{ITEM_TOKEN[item]}", redis_client, person_box=box)
                elif transition == "detected":
                    ps[item].proof = None
            out[pid] = {ITEM_TOKEN[item]: _to_person_status(ps[item].confirmed) for item in ITEMS}

        # Forget people who have left so stale state doesn't accumulate.
        for gone in [pid for pid in self.person_states if pid not in persons_cam_boxes]:
            self.person_states.pop(gone, None)
        self.last_person_status = out
        return out

    def process(self, frame: np.ndarray, redis_client, person_boxes: List[Box],
                now: Optional[float] = None) -> dict:
        """Run one PPE detection + association + debounce step; write Redis (hash-gated).

        `person_boxes` are full-body person boxes (x1,y1,x2,y2) from the caller's COCO
        detector, in the same pixel space as `frame`. They drive gating + association;
        the OIV7 model here only contributes backpack/hat boxes.
        """
        now = now or time.time()

        body_boxes, hat_boxes, face_boxes, head_anchor_boxes = self._detect(frame)
        persons = list(person_boxes or [])
        self.last_boxes = {"person": persons, "body": body_boxes, "head": hat_boxes,
                           "face": face_boxes}

        person_present = len(persons) > 0
        if not person_present:
            raw = {"body_gear": NO_PERSON, "head_protection": NO_PERSON}
        else:
            is_body = body_worn(body_boxes, persons)
            is_head = head_worn(hat_boxes, head_anchor_boxes, face_boxes, persons)
            raw = {"body_gear": WORN if is_body else NOT_WORN,
                   "head_protection": WORN if is_head else NOT_WORN}

        for item in ITEMS:
            transition = self.states[item].update(raw[item], now)
            if transition == "missing":
                self.states[item].proof = save_proof_frame(frame, item, redis_client)
            elif transition == "detected":
                self.states[item].proof = None  # cleared once compliant again

        payload = {
            "person_present": person_present,
            **{item: {"status": self.states[item].confirmed,
                      "since": round(self.states[item].since, 2),
                      "proof": self.states[item].proof}
               for item in ITEMS},
        }

        serialized = json.dumps(payload, sort_keys=True)
        if serialized != self._prev_payload and redis_client is not None:
            self._prev_payload = serialized
            try:
                redis_client.set(PPE_KEY, json.dumps(payload))
            except Exception as e:
                print(f"[ppe] redis write failed: {e}")
        return payload

    def annotate(self, frame: np.ndarray) -> None:
        """Draw the latest boxes + per-item status onto `frame` (for preview windows)."""
        for (x1, y1, x2, y2) in self.last_boxes["person"]:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (90, 90, 90), 1)
        for (x1, y1, x2, y2) in self.last_boxes.get("body", []):
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)
        for (x1, y1, x2, y2) in self.last_boxes["head"]:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 255), 2)
        colors = {"detected": (0, 200, 0), "missing": (0, 0, 220),
                  "no_person": (150, 150, 150), "unknown": (180, 180, 180)}
        for i, item in enumerate(ITEMS):
            s = self.states[item]
            cv2.putText(frame, f"{item}: {s.confirmed.upper()}", (12, 30 + i * 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        colors.get(s.confirmed, (200, 200, 200)), 2, cv2.LINE_AA)
