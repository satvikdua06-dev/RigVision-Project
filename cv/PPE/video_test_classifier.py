import os
import argparse
import json
import torch
import torch.nn as nn
import cv2
from PIL import Image
from torchvision import models, transforms
from huggingface_hub import hf_hub_download
from ultralytics import YOLO


# ── Load EfficientNet-B0 classifier ──────────────────────────────────────────
def load_classifier(model_dir: str, device: torch.device):
    config_path = os.path.join(model_dir, "config.json")
    with open(config_path) as f:
        config = json.load(f)

    m = models.efficientnet_b0(weights=None)
    in_features = m.classifier[1].in_features
    m.classifier = nn.Sequential(
        nn.Dropout(p=0.3, inplace=True),
        nn.Linear(in_features, 2),
    )
    m.load_state_dict(torch.load(os.path.join(model_dir, "best_model.pth"), map_location=device))
    m.to(device).eval()
    return m, config


def build_transform(img_size: int = 224):
    return transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std =[0.229, 0.224, 0.225]),
    ])


def classify(model, transform, crop_bgr, device, threshold=0.5):
    """Returns (present: bool, confidence: float)."""
    rgb  = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    img  = Image.fromarray(rgb)
    x    = transform(img).unsqueeze(0).to(device)
    with torch.no_grad():
        probs = torch.softmax(model(x), dim=1)[0]
    conf    = probs[1].item()   # probability of class 1 = "present"
    return conf >= threshold, conf


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Two-stage PPE classifier test: yolov8n-face → EfficientNet-B0."
    )
    parser.add_argument("--input",       type=str, required=True,
                        help="Path to input video file (or '0' for webcam).")
    parser.add_argument("--output",      type=str, default=None,
                        help="Path to save annotated output video (optional).")
    parser.add_argument("--cap-dir",     type=str, default="./cap_classifier",
                        help="Directory of the trained cap classifier.")
    parser.add_argument("--glasses-dir", type=str, default=None,
                        help="Directory of the trained glasses classifier (optional).")
    parser.add_argument("--face-model",  type=str, default="yolov8n-face.pt",
                        help="Local path to yolov8n-face.pt, or leave default to auto-download.")
    parser.add_argument("--face-conf",   type=float, default=0.5)
    parser.add_argument("--cap-conf",    type=float, default=0.5,
                        help="Probability threshold for cap present (default 0.5).")
    parser.add_argument("--glasses-conf",type=float, default=0.5)
    parser.add_argument("--pad-top",     type=float, default=0.3)
    parser.add_argument("--pad-bottom",  type=float, default=0.1)
    parser.add_argument("--pad-left",    type=float, default=0.2)
    parser.add_argument("--pad-right",   type=float, default=0.2)
    parser.add_argument("--no-show",     action="store_true")
    parser.add_argument("--width",       type=int, default=1280,
                        help="Requested capture width (default 1280).")
    parser.add_argument("--height",      type=int, default=720,
                        help="Requested capture height (default 720).")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ── Face model ──
    print("Loading face detection model...")
    face_path = args.face_model
    if not os.path.exists(face_path):
        print("  Downloading yolov8n-face.pt from HuggingFace Hub...")
        face_path = hf_hub_download(repo_id="ElenaRyumina/MASAI_models",
                                    filename="yolov8n-face.pt")
    face_model = YOLO(face_path)
    face_model.to(device)

    # ── Cap classifier ──
    print(f"Loading cap classifier from {args.cap_dir} ...")
    cap_model, cap_cfg = load_classifier(args.cap_dir, device)
    tf = build_transform(cap_cfg.get("img_size", 224))
    print(f"  item={cap_cfg['item']}  val_accuracy={cap_cfg.get('val_accuracy','?')}")

    # ── Glasses classifier (optional) ──
    glasses_model = None
    if args.glasses_dir and os.path.isdir(args.glasses_dir):
        print(f"Loading glasses classifier from {args.glasses_dir} ...")
        glasses_model, glasses_cfg = load_classifier(args.glasses_dir, device)
        print(f"  item={glasses_cfg['item']}  val_accuracy={glasses_cfg.get('val_accuracy','?')}")

    # ── Video ──
    src = 0 if args.input == "0" else args.input
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"Error: cannot open {args.input}")
        return

    # Request resolution for live sources (webcam / RTSP); ignored for video files
    if isinstance(src, int) or str(src).startswith("rtsp"):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video: {width}x{height} @ {fps:.1f} fps, {total} frames")

    writer = None
    if args.output:
        writer = cv2.VideoWriter(
            args.output, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )

    WINDOW = 90   # frames = ~3 seconds at 30fps (matches pipeline debounce)
    cap_scores    = []
    glasses_scores = []

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1
            draw = frame.copy()

            face_results = face_model.predict(source=frame, conf=args.face_conf,
                                              verbose=False)[0]

            for face_box in face_results.boxes:
                fx1, fy1, fx2, fy2 = map(int, face_box.xyxy[0].tolist())
                fw, fh = fx2 - fx1, fy2 - fy1

                # Padded crop for PPE (captures cap crown above face)
                cx1 = max(0,      fx1 - int(fw * args.pad_left))
                cy1 = max(0,      fy1 - int(fh * args.pad_top))
                cx2 = min(width,  fx2 + int(fw * args.pad_right))
                cy2 = min(height, fy2 + int(fh * args.pad_bottom))

                if (cx2 - cx1) <= 0 or (cy2 - cy1) <= 0:
                    continue

                crop = frame[cy1:cy2, cx1:cx2]

                # Face box (grey)
                cv2.rectangle(draw, (fx1, fy1), (fx2, fy2), (150, 150, 150), 1)
                # PPE crop box (light blue)
                cv2.rectangle(draw, (cx1, cy1), (cx2, cy2), (255, 200, 100), 1)

                # ── Cap classification ──
                cap_present, cap_prob = classify(
                    cap_model, tf, crop, device, args.cap_conf
                )
                cap_scores.append(cap_prob)
                if len(cap_scores) > WINDOW:
                    cap_scores.pop(0)
                cap_avg     = sum(cap_scores) / len(cap_scores)
                cap_commit  = cap_avg >= args.cap_conf
                cap_color   = (0, 220, 0) if cap_commit else (0, 0, 220)
                cap_label   = f"cap: {'YES' if cap_commit else 'NO'} (raw={cap_prob:.2f} avg={cap_avg:.2f})"

                # ── Glasses classification (if loaded) ──
                lines  = [cap_label]
                colors = [cap_color]
                if glasses_model is not None:
                    g_present, g_prob = classify(
                        glasses_model, tf, crop, device, args.glasses_conf
                    )
                    glasses_scores.append(g_prob)
                    if len(glasses_scores) > WINDOW:
                        glasses_scores.pop(0)
                    g_avg    = sum(glasses_scores) / len(glasses_scores)
                    g_commit = g_avg >= args.glasses_conf
                    g_color  = (0, 220, 0) if g_commit else (0, 0, 220)
                    lines.append(f"glasses: {'YES' if g_commit else 'NO'} (raw={g_prob:.2f} avg={g_avg:.2f})")
                    colors.append(g_color)

                # Draw labels stacked above the crop box
                for i, (line, color) in enumerate(zip(lines, colors)):
                    y = max(cy1 - 10 - i * 22, 14)
                    cv2.putText(draw, line, (cx1, y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

                print(f"[{frame_idx:05d}] cap raw={cap_prob:.2f} avg={cap_avg:.2f}"
                      + (f"  gl raw={g_prob:.2f} avg={g_avg:.2f}" if glasses_model else ""))

            if writer:
                writer.write(draw)

            if not args.no_show:
                cv2.imshow("PPE Classifier", draw)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("Interrupted by user.")
                    break

            if frame_idx % 100 == 0:
                print(f"--- {frame_idx}/{total} frames processed ---")

    finally:
        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()
