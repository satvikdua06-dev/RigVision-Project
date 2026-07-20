"""
Find the frame offset between two videos by stepping through them manually.

CONTROLS
    LEFT / RIGHT   — step cam0 backward / forward 1 frame
    A / D          — step cam1 backward / forward 1 frame
    Q              — quit and print the offset
"""
import cv2
import sys

LEFT  = 2424832
RIGHT = 2555904

def main():
    if len(sys.argv) < 3:
        print("Usage: python find_video_offset.py video0.mp4 video1.mp4")
        return

    cap0 = cv2.VideoCapture(sys.argv[1])
    cap1 = cv2.VideoCapture(sys.argv[2])

    if not cap0.isOpened() or not cap1.isOpened():
        print("Could not open one or both videos.")
        return

    def get_frame(cap, pos):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, pos))
        ret, frame = cap.read()
        return frame if ret else None

    pos0, pos1 = 0, 0

    print("LEFT/RIGHT = cam0 back/forward | A/D = cam1 back/forward | Q = done")
    print("Align a common moment visible in both cameras, then press Q.\n")

    while True:
        f0 = get_frame(cap0, pos0)
        f1 = get_frame(cap1, pos1)

        if f0 is None or f1 is None:
            break

        h = 360
        f0r = cv2.resize(f0, (int(f0.shape[1] * h / f0.shape[0]), h))
        f1r = cv2.resize(f1, (int(f1.shape[1] * h / f1.shape[0]), h))

        cv2.putText(f0r, f"CAM 0  frame={pos0}  (LEFT/RIGHT)", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(f1r, f"CAM 1  frame={pos1}  offset={pos1-pos0}  (A/D)", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        combined = cv2.hconcat([f0r, f1r])
        cv2.imshow("Sync Finder — LEFT/RIGHT=cam0   A/D=cam1   Q=done", combined)

        key = cv2.waitKeyEx(0)
        if key == ord('q'):
            break
        elif key == RIGHT:
            pos0 += 1
        elif key == LEFT:
            pos0 = max(0, pos0 - 1)
        elif key == ord('d'):
            pos1 += 1
        elif key == ord('a'):
            pos1 = max(0, pos1 - 1)

    offset = pos1 - pos0
    cap0.release()
    cap1.release()
    cv2.destroyAllWindows()

    print(f"\nOffset: cam1 is {offset} frames ahead of cam0")
    if offset > 0:
        print(f"Use: --video-offsets 1={offset}")
    elif offset < 0:
        print(f"Use: --video-offsets 0={-offset}")
    else:
        print("Videos are already in sync — no offset needed.")

if __name__ == "__main__":
    main()
