"""Synthetic check for mosaic.py: render a walk over a procedurally generated floor, stitch it, and report
the keyframe position error against ground truth. No camera needed.

  python drone/test_mosaic_synth.py                    # carpet-like texture (contrast 8)
  python drone/test_mosaic_synth.py --contrast 3       # nearly plain floor (hard case)
  python drone/test_mosaic_synth.py --save data/synth  # also write the video and mosaic
"""
import argparse
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mosaic import Mosaicker  # noqa: E402

MM_PER_PX = 4.2          # Camera Module 3 Wide at 2.2 m, 1280 px across ~5.4 m of floor
FRAME_W, FRAME_H = 1280, 720


def make_floor(w, h, contrast, rng):
    """Carpet-like band-limited noise + a few dark node-sized boxes + a strip of tape."""
    noise = rng.normal(0, 1, (h, w)).astype(np.float32)
    fine = cv2.GaussianBlur(noise, (0, 0), 1.2)
    coarse = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), 12)
    g = 128 + contrast * (fine / fine.std()) + 2 * contrast * (coarse / coarse.std())
    img = cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    img = (img * np.array([0.9, 0.85, 1.0])).astype(np.uint8)  # NoIR-ish colour cast
    for _ in range(4):  # node cases ~100 x 66 mm
        x, y = int(rng.uniform(300, w - 300)), int(rng.uniform(200, h - 200))
        cv2.rectangle(img, (x, y), (x + 24, y + 16), (40, 40, 40), -1)
    cv2.line(img, (200, h // 2), (w - 200, h // 2 + 40), (200, 200, 210), 4)
    return img


def walk(floor, n, speed_px, rng):
    """Lawnmower-ish path: straight leg, U-turn, back. Yields (frame, true 2x3 frame->floor)."""
    h, w = floor.shape[:2]
    y_legs = [h * 0.33, h * 0.62]
    leg_len = w - FRAME_W - 200
    for i in range(n):
        d = i * speed_px
        leg = int(d // leg_len) % 2
        f = (d % leg_len) / leg_len
        x = 100 + FRAME_W / 2 + (f if leg == 0 else 1 - f) * leg_len
        y = y_legs[leg] + 15 * math.sin(i / 9)
        ang = math.radians(6 * math.sin(i / 23) + (180 if leg else 0) * 0)  # hand wobble
        s = 1 + 0.04 * math.sin(i / 31)                                    # height wobble +-4 %
        A = cv2.getRotationMatrix2D((x, y), math.degrees(ang), s)          # floor -> rotated floor
        # frame pixel (u, v) -> floor: centre the frame at (x, y)
        Ainv = cv2.invertAffineTransform(A)
        T = np.vstack([Ainv, [0, 0, 1]]) @ np.array([[1, 0, x - FRAME_W / 2], [0, 1, y - FRAME_H / 2], [0, 0, 1]])
        frame = cv2.warpAffine(floor, cv2.invertAffineTransform(T[:2]), (FRAME_W, FRAME_H), flags=cv2.INTER_LINEAR)
        k = np.zeros((1, 7), np.float32); k[0, :] = 1 / 7  # horizontal motion blur
        frame = cv2.filter2D(frame, -1, k)
        frame = np.clip(frame + rng.normal(0, 3, frame.shape), 0, 255).astype(np.uint8)
        yield frame, T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contrast", type=float, default=8.0, help="floor texture std, grey levels")
    ap.add_argument("--frames", type=int, default=420)
    ap.add_argument("--speed", type=float, default=4.0, help="px/frame (4 px = 17 mm = 0.5 m/s at 30 fps)")
    ap.add_argument("--save", default=None)
    a = ap.parse_args()
    rng = np.random.default_rng(7)
    floor = make_floor(3600, 1800, a.contrast, rng)
    m = Mosaicker(work_width=640)
    truth = []
    writer = None
    for i, (frame, T) in enumerate(walk(floor, a.frames, a.speed, rng)):
        if a.save and writer is None:
            writer = cv2.VideoWriter(a.save + ".mp4", cv2.VideoWriter_fourcc(*"mp4v"), 30, (FRAME_W, FRAME_H))
        if writer is not None:
            writer.write(frame)
        if i % 2:
            continue
        if m.add(frame) == "keyframe":
            truth.append(T)
    if writer is not None:
        writer.release()
    # compare keyframe centres: estimate (in frame-0 work px) vs truth (floor px -> frame-0 px)
    k = 640 / FRAME_W
    T0inv = np.linalg.inv(truth[0])
    errs = []
    for (img, Test), Ttrue in zip(m.keyframes, truth):
        c = np.array([FRAME_W / 2 * k, FRAME_H / 2 * k, 1])
        est = Test @ c
        true = (T0inv @ Ttrue @ np.array([FRAME_W / 2, FRAME_H / 2, 1])) * k
        errs.append(math.hypot(est[0] - true[0], est[1] - true[1]) / k * MM_PER_PX / 10)  # cm
    span = max(math.hypot(*(T0inv @ t @ [FRAME_W / 2, FRAME_H / 2, 1])[:2] - np.array([FRAME_W / 2, FRAME_H / 2]))
               for t in truth) * MM_PER_PX / 1000
    print(f"contrast {a.contrast}: {len(m.keyframes)} keyframes, lost {m.stats['lost']}/{m.stats['frames']} frames, "
          f"walk span {span:.1f} m, position error median {np.median(errs):.1f} cm, max {max(errs):.1f} cm")
    if a.save:
        img, _ = m.render()
        cv2.imwrite(a.save + "_mosaic.png", img)
        print("wrote", a.save + ".mp4", a.save + "_mosaic.png")


if __name__ == "__main__":
    main()
