"""mosaic.py: stitch a downward-looking walk/flight video into one top-down image of the floor.

Classical computer vision, no training: per frame, find SIFT features (after a CLAHE contrast boost, which
helps on plain carpet/tile), match them to the last keyframe, fit a rotation+translation+scale model with
RANSAC (a downward camera over a flat floor moves like that), chain the transforms, and feather-blend
keyframes onto a canvas. Same code on the laptop (development) and the Raspberry Pi 5 (live).

  python drone/mosaic.py walk.mp4 --out data/mosaic_test               # stitch a video file
  python drone/mosaic.py walk.mp4 --out data/mosaic_test --hfov 69     # phone main camera (~69 deg)
  python drone/mosaic.py walk.mp4 --out ... --align 812,640=0,0 --align 1290,655=3,0   # pin to the heatmap
  python drone/mosaic.py data/camera/walk2/%06d.jpg --out ...  # a frame folder recorded by live_mosaic.py

Outputs <out>.png and <out>.json:
  {"width", "height", "m_per_px", "px_to_m": [[a,b,c],[d,e,f]], "aligned": bool, "keyframes", ...}
  px_to_ref maps a mosaic pixel to the first frame's pixels, which never move as a live mosaic grows
  (store alignments in those coordinates).
  px_to_m maps a mosaic pixel (u, v, 1) to heatmap metres (x, y). Before alignment it uses the camera
  height and field of view (x right, y up, origin at the first frame's centre); after --align with two
  known points (e.g. nodes N1 and N2) it is exact in position, rotation and scale.
"""
import argparse
import json
import math
import time

import cv2
import numpy as np


class Mosaicker:
    def __init__(self, work_width=640, keyframe_shift=0.25, min_inliers=25, undistort=None, mask_bottom=0.0,
                 fixed_scale=True):
        self.work_width = work_width
        self.fixed_scale = fixed_scale        # camera height ~constant: estimate rotation + shift only
        self.mask_bottom = mask_bottom        # ignore features in this bottom fraction (the carrier's feet)
        self._mask = None
        self.keyframe_shift = keyframe_shift  # new keyframe after moving this fraction of the frame width
        self.min_inliers = min_inliers
        self.undistort = undistort            # optional (K, dist) at work resolution
        self.sift = cv2.SIFT_create(nfeatures=1500)
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        self.matcher = cv2.BFMatcher(cv2.NORM_L2)
        self.keyframes = []                   # (image_bgr, 3x3 transform frame->reference)
        self.last = None                      # (kp, des, T_ref) of the last frame that tracked
        self.kf_feats = []                    # (kp, des, T) per keyframe, to re-find our place after a loss
        self.lost_run = 0                     # consecutive lost frames
        self.restart_after = 10               # lost frames before a tiny (<= 3 keyframe) mosaic restarts
        self.stats = {"frames": 0, "lost": 0}

    def _prep(self, frame):
        h, w = frame.shape[:2]
        if w != self.work_width:
            frame = cv2.resize(frame, (self.work_width, round(h * self.work_width / w)), interpolation=cv2.INTER_AREA)
        if self.undistort is not None:
            frame = cv2.undistort(frame, *self.undistort)
        gray = self.clahe.apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        if self.mask_bottom and (self._mask is None or self._mask.shape != gray.shape):
            self._mask = np.full(gray.shape, 255, np.uint8)
            self._mask[int(gray.shape[0] * (1 - self.mask_bottom)):] = 0
        kp, des = self.sift.detectAndCompute(gray, self._mask if self.mask_bottom else None)
        return frame, kp, des

    def _relative(self, kp, des, ref):
        """3x3 transform mapping this frame's pixels into the pixels of ref = (kp, des, T), or None."""
        lkp, ldes, _ = ref
        if des is None or ldes is None or len(kp) < 8:
            return None, 0
        pairs = self.matcher.knnMatch(des, ldes, k=2)
        good = [m for m, *n in pairs if n and m.distance < 0.75 * n[0].distance]
        if len(good) < self.min_inliers:
            return None, len(good)
        src = np.float32([kp[m.queryIdx].pt for m in good])
        dst = np.float32([lkp[m.trainIdx].pt for m in good])
        A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        n_in = int(inl.sum()) if inl is not None else 0
        if A is None or n_in < self.min_inliers:
            return None, n_in
        s = math.hypot(A[0, 0], A[1, 0])
        if not 0.8 < s < 1.25:  # height changes this fast are mismatches, not motion
            return None, n_in
        if self.fixed_scale:
            # Constant height (drone holding altitude, arm overhead): keep only rotation + shift. Small tilts
            # otherwise look like zooming, and that error compounds over a walk (the map shrinks).
            A[:, :2] /= s
        return np.vstack([A, [0, 0, 1]]), n_in

    def add(self, frame):
        """Feed one BGR frame. Returns 'keyframe', 'tracked' or 'lost'.

        Each frame is matched to the last frame that tracked (not the last keyframe: overlap with the
        previous frame stays high even when the view tilts), and the motions are chained. A frame becomes a
        keyframe once its centre has moved keyframe_shift x frame width from the last keyframe's centre.
        After a lost frame, the next one is matched to the same last good frame, so short gaps recover."""
        self.stats["frames"] += 1
        img, kp, des = self._prep(frame)
        if self.last is None or (len(self.keyframes) <= 3 and self.lost_run >= self.restart_after):
            # Start, or lost for a while with only a tiny mosaic (the desk, the lift-off): (re)start here.
            self.keyframes[:], self.kf_feats[:] = [(img, np.eye(3))], [(kp, des, np.eye(3))]
            self.last, self.lost_run = (kp, des, np.eye(3)), 0
            return "keyframe"
        R, n_in = self._relative(kp, des, self.last)
        base = self.last
        if R is None:  # lost: try to re-find a place we have already mapped (newest keyframes first)
            for feats in reversed(self.kf_feats[-8:]):
                R, n_in = self._relative(kp, des, feats)
                if R is not None:
                    base = feats
                    break
        if R is None:
            self.stats["lost"] += 1
            self.lost_run += 1
            return "lost"
        self.lost_run = 0
        T = base[2] @ R
        self.last = (kp, des, T)
        h, w = img.shape[:2]
        c = np.array([w / 2, h / 2, 1.0])
        if min(np.linalg.norm((T @ c)[:2] - (Tk @ c)[:2]) for _, Tk in self.keyframes[-8:]) < self.keyframe_shift * w:
            return "tracked"
        self.keyframes.append((img, T))
        self.kf_feats.append((kp, des, T))
        return "keyframe"

    def render(self, max_side=4000):
        """Feather-blended mosaic. Returns (image, M) where M maps reference px -> mosaic px (3x3)."""
        h, w = self.keyframes[0][0].shape[:2]
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        pts = np.vstack([cv2.perspectiveTransform(corners, T) for _, T in self.keyframes]).reshape(-1, 2)
        x0, y0 = np.floor(pts.min(0)); x1, y1 = np.ceil(pts.max(0))
        scale = min(1.0, max_side / max(x1 - x0, y1 - y0))
        M = np.array([[scale, 0, -x0 * scale], [0, scale, -y0 * scale], [0, 0, 1]])
        W, H = int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1
        acc = np.zeros((H, W, 3), np.float32)
        wsum = np.zeros((H, W), np.float32)
        # feather weight: 1 in the middle of a frame, 0 at its edges
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        feather = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy))
        feather = np.clip(feather / (0.15 * min(w, h)), 0, 1) + 1e-3
        if self.mask_bottom:  # and leave the carrier's feet out of the picture
            feather[int(h * (1 - self.mask_bottom)):] = 0
        for img, T in self.keyframes:
            A = (M @ T)[:2]
            acc += cv2.warpAffine(img.astype(np.float32) * feather[..., None], A, (W, H))
            wsum += cv2.warpAffine(feather, A, (W, H))
        out = (acc / np.maximum(wsum, 1e-6)[..., None]).astype(np.uint8)
        out[wsum < 1e-3] = 0
        return out, M


def default_px_to_m(M, work_width, frame_h, hfov_deg, height_m):
    """Mosaic px -> metres from camera geometry: origin at the first frame's centre, x right, y up."""
    fx = (work_width / 2) / math.tan(math.radians(hfov_deg) / 2)
    m_per_ref_px = height_m / fx
    c = np.array([work_width / 2, frame_h / 2, 1.0])
    Minv = np.linalg.inv(M)  # mosaic px -> reference px
    S = np.array([[m_per_ref_px, 0, -m_per_ref_px * c[0]], [0, -m_per_ref_px, m_per_ref_px * c[1]], [0, 0, 1]])
    return (S @ Minv)[:2], m_per_ref_px / M[0, 0]


def align_two_points(p1, q1, p2, q2):
    """Similarity transform mapping mosaic pixels p1,p2 to metres q1,q2 (y up). Returns 2x3, m_per_px."""
    p1, q1, p2, q2 = (np.array(v, float) for v in (p1, q1, p2, q2))
    dp, dq = p2 - p1, q2 - q1
    # pixels have y down; flip to y up before solving the rotation
    dp_up = np.array([dp[0], -dp[1]])
    s = np.linalg.norm(dq) / np.linalg.norm(dp_up)
    ang = math.atan2(dq[1], dq[0]) - math.atan2(dp_up[1], dp_up[0])
    c, si = s * math.cos(ang), s * math.sin(ang)
    R = np.array([[c, -si], [si, c]]) @ np.array([[1, 0], [0, -1]])  # px (y down) -> metres (y up)
    t = q1 - R @ p1
    return np.hstack([R, t[:, None]]), s


def stitch_video(path, step=1, max_frames=None, **kw):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {path}")
    m = Mosaicker(**kw)
    i = 0
    t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok or (max_frames and i >= max_frames):
            break
        if i % step == 0:
            m.add(frame)
        i += 1
    m.stats["seconds"] = round(time.time() - t0, 1)
    return m


def main():
    ap = argparse.ArgumentParser(description="Stitch a downward-looking video into a top-down mosaic.")
    ap.add_argument("video")
    ap.add_argument("--out", required=True, help="output prefix, e.g. data/mosaic_test")
    ap.add_argument("--step", type=int, default=2, help="use every Nth frame")
    ap.add_argument("--work-width", type=int, default=640)
    ap.add_argument("--hfov", type=float, default=102.0, help="horizontal field of view (Camera Module 3 Wide: 102)")
    ap.add_argument("--height", type=float, default=2.2, help="camera height above the floor, metres")
    ap.add_argument("--align", action="append", default=[], help="PX,PY=X,Y (mosaic pixel = heatmap metres), twice")
    ap.add_argument("--mask-bottom", type=float, default=0.0, help="ignore this bottom fraction (hand-carried: ~0.2)")
    a = ap.parse_args()

    m = stitch_video(a.video, step=a.step, work_width=a.work_width, mask_bottom=a.mask_bottom)
    if not m.keyframes:
        raise SystemExit("no frames")
    img, M = m.render()
    h0 = m.keyframes[0][0].shape[0]
    px_to_m, m_per_px = default_px_to_m(M, a.work_width, h0, a.hfov, a.height)
    aligned = False
    if len(a.align) == 2:
        (p1, q1), (p2, q2) = [[tuple(map(float, s.split(","))) for s in x.split("=")] for x in a.align]
        px_to_m, m_per_px = align_two_points(p1, q1, p2, q2)
        aligned = True
    cv2.imwrite(a.out + ".png", img)
    meta = {"width": img.shape[1], "height": img.shape[0], "m_per_px": round(float(m_per_px), 5),
            "px_to_m": np.round(px_to_m, 6).tolist(), "px_to_ref": np.round(np.linalg.inv(M)[:2], 6).tolist(),
            "aligned": aligned, "keyframes": len(m.keyframes),
            "source": a.video, "stats": m.stats, "hfov_deg": a.hfov, "height_m": a.height}
    with open(a.out + ".json", "w") as f:
        json.dump(meta, f, indent=1)
    print(f"{len(m.keyframes)} keyframes from {m.stats['frames']} frames "
          f"(lost {m.stats['lost']}) in {m.stats['seconds']} s -> {a.out}.png {img.shape[1]}x{img.shape[0]} px, "
          f"{m_per_px * 100:.2f} cm/px, aligned={aligned}")


if __name__ == "__main__":
    main()
