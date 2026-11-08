"""make_media.py: regenerate the media/ folder (photos, mosaics, map-building video + GIF, diagram) from the repo.

  python tools/make_media.py --photos DIR      # also import device photos / screenshots from DIR (see PHOTOS below)

Browser screenshots of the live pages are taken separately (they need the servers running): see media/README.md.
"""
import argparse
import glob
import os
import shutil
import sys

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "drone"))
from mosaic import Mosaicker  # noqa: E402

MEDIA = os.path.join(ROOT, "media")
# source file in --photos DIR -> (media path, caption)
PHOTOS = {
    "3.jpg": ("photos/hardware_angle.jpg", "Sensor nodes (ESP32-C5 + Grove sound sensor, SW-420 vibration switch, buzzer), the gateway and the Pi 5 'drone' with its downward camera, plus printed node shells"),
    "4.jpg": ("photos/hardware_top.jpg", "Top view: three nodes on the board, the XIAO ESP32-S3 gateway on USB to the Pi 5 (camera ribbon, 'DRONE' tag), two loose nodes and the node enclosures"),
    "5.jpg": ("photos/hardware_side.jpg", "The full kit on the table"),
    "6.jpg": ("photos/node_closeup.jpg", "One node close up: XIAO ESP32-C5 with antenna, Grove sound sensor, SW-420 vibration switch and buzzer on a breadboard"),
    "1.png": ("screenshots/wintak_first_test_zoomed.png", "WinTAK, first TAK test (simulator): node markers T10 N1/N2, N5 shown LOST, and the heatmap estimate (then a search-area marker; now 'T10 LOOK HERE')"),
    "2.png": ("screenshots/wintak_first_test_venue.png", "WinTAK zoomed out over the venue: our T10 N1 next to other teams' markers on the shared SA network"),
}


def out(rel):
    p = os.path.join(MEDIA, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def import_photos(src):
    for name, (rel, _) in PHOTOS.items():
        f = os.path.join(src, name)
        if not os.path.exists(f):
            continue
        im = Image.open(f)
        im = im.convert("RGB") if rel.endswith(".jpg") else im
        im.thumbnail((1600, 1600))
        im.save(out(rel), quality=85) if rel.endswith(".jpg") else im.save(out(rel), optimize=True)
        print("photo", rel)


def mosaics():
    for name in ("walk3_mosaic.png", "walk2_restitch.png"):
        f = os.path.join(ROOT, "data", "camera", name)
        if os.path.exists(f):
            shutil.copy(f, out("mosaic/" + name))
            print("mosaic", name)
    frames = sorted(glob.glob(os.path.join(ROOT, "data", "camera", "walk2", "*.jpg")))
    if frames:  # walk 2: the tilted hand-held frames that taught us to point the camera straight down
        picks = np.linspace(0, len(frames) - 1, 8).astype(int)
        tiles = [cv2.resize(cv2.imread(frames[i]), (400, 225)) for i in picks]
        cv2.imwrite(out("mosaic/walk2_tilted_frames.jpg"), np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))


def fit(img, w, h, bg=(24, 24, 24)):
    """Letterbox img into w x h."""
    k = min(w / img.shape[1], h / img.shape[0])
    im = cv2.resize(img, (max(1, int(img.shape[1] * k)), max(1, int(img.shape[0] * k))), interpolation=cv2.INTER_AREA)
    canvas = np.full((h, w, 3), bg, np.uint8)
    y, x = (h - im.shape[0]) // 2, (w - im.shape[1]) // 2
    canvas[y:y + im.shape[0], x:x + im.shape[1]] = im
    return canvas, k, x, y


def label(img, text, org, scale=0.7, color=(255, 255, 255)):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def build_video(walk="walk3", drop_at=(0.12, 0.45, 0.8), ids=(1, 2, 5)):
    """Replay a recorded walk through the stitcher: live frame (with the drop crosshair) | growing mosaic with drops."""
    frames = sorted(glob.glob(os.path.join(ROOT, "data", "camera", walk, "*.jpg")))
    if not frames:
        print("no frames for", walk)
        return
    W, H = 1280, 720
    m = Mosaicker(mask_bottom=0.3)
    drops, video, gif = [], [], []
    drop_frames = {int(f * len(frames)): i for i, f in zip(ids, drop_at)}
    pano, M = None, None
    for n, f in enumerate(frames):
        frame = cv2.imread(f)
        r = m.add(frame)
        hh, ww = m.keyframes[0][0].shape[:2]
        here = (m.last[2] @ [ww / 2, hh / 2, 1.0])[:2] if r != "lost" else None
        if n in drop_frames and here is not None:
            drops.append((drop_frames[n], here, n))
        if r == "keyframe" or pano is None or (drops and drops[-1][2] == n):
            pano, M = m.render(max_side=1400)
        # left: live frame with crosshair; right: mosaic so far with dropped nodes
        left = cv2.resize(frame, (560, 315))
        cv2.drawMarker(left, (280, 157), (0, 255, 255), cv2.MARKER_CROSS, 30, 2)
        if r == "lost":
            label(left, "LOST", (12, 30), 0.8, (60, 60, 255))
        right, k, ox, oy = fit(pano, 700, 690)
        for nid, ref, _ in drops:
            u, v = (M @ [ref[0], ref[1], 1.0])[:2]
            p = (int(ox + u * k), int(oy + v * k))
            cv2.circle(right, p, 11, (80, 200, 80), -1)
            cv2.circle(right, p, 11, (255, 255, 255), 2)
            label(right, f"N{nid}", (p[0] + 14, p[1] - 8), 0.7)
        canvas = np.full((H, W, 3), 17, np.uint8)
        canvas[60:375, 20:580] = left
        canvas[15:705, 560:1260] = right
        label(canvas, "Team 10: drone camera builds the map, nodes placed where they drop", (20, 35), 0.75)
        label(canvas, "camera (+ = drop point)", (20, 400), 0.6, (200, 200, 200))
        dropped_now = [d for d in drops if n - d[2] < 15]
        if dropped_now:
            label(canvas, f"DROP: N{dropped_now[-1][0]}", (20, 460), 1.1, (80, 220, 255))
        label(canvas, f"frame {n + 1}/{len(frames)}  keyframes {len(m.keyframes)}  lost {m.stats['lost']}",
              (20, 690), 0.55, (170, 170, 170))
        video.append(canvas)
        if n % 2 == 0:
            video[-1] = cv2.resize(canvas, (960, 540), interpolation=cv2.INTER_AREA)
        else:
            video.pop()  # every 2nd frame at 6 fps keeps the file small (and the walk at ~real speed)
        if n % 4 == 0:
            g = Image.fromarray(cv2.cvtColor(cv2.resize(canvas, (480, 270), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
            gif.append(g.quantize(colors=96, method=Image.Quantize.MEDIANCUT))
    for fourcc, ext in (("avc1", ".mp4"), ("mp4v", ".mp4")):  # H.264 if this OpenCV build has it, else MPEG-4
        path = out(f"video/mosaic_build_{walk}{ext}")
        vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*fourcc), 6, (960, 540))
        if vw.isOpened():
            for c in video + [video[-1]] * 18:
                vw.write(c)
            vw.release()
            print("video", path, fourcc)
            break
    gif[0].save(out(f"gifs/mosaic_build_{walk}.gif"), save_all=True, append_images=gif[1:] + [gif[-1]] * 10,
                duration=250, loop=0, optimize=True)
    cv2.imwrite(out(f"mosaic/{walk}_with_drops.png"), canvas)
    print("gif + final frame for", walk)


def synthetic():
    sys.argv = ["test_mosaic_synth.py", "--frames", "300", "--save", os.path.join(MEDIA, "mosaic", "synthetic")]
    sys.path.insert(0, os.path.join(ROOT, "drone"))
    import test_mosaic_synth
    test_mosaic_synth.main()
    os.remove(os.path.join(MEDIA, "mosaic", "synthetic.mp4"))  # keep the mosaic, not the raw synthetic video


def diagram():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
    fig, ax = plt.subplots(figsize=(14, 6.4), dpi=130)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6.4)
    ax.axis("off")
    fig.patch.set_facecolor("#111")

    def box(x, y, w, h, title, lines, color):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.15",
                                    fc="#1d1d1d", ec=color, lw=2))
        ax.text(x + w / 2, y + h - 0.32, title, ha="center", va="center", color=color, fontsize=12, weight="bold")
        for i, ln in enumerate(lines):
            ax.text(x + 0.15, y + h - 0.75 - i * 0.36, ln, ha="left", va="center", color="#ddd", fontsize=9)

    def arrow(a, b, text, color="#aaa", dy=0.18):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=16, color=color, lw=1.8))
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, text, ha="center", color=color, fontsize=8.5)

    box(0.2, 3.3, 3.0, 2.8, "Sensor nodes (x5)", ["XIAO ESP32-C5, ~$15", "sound sensor: loudness, onsets,",
        "  sustained sound", "SW-420: taps, tap patterns", "buzzer: HAIL beeps", "BLE / Wi-Fi device scan"], "#4c4")
    box(0.2, 0.3, 3.0, 2.5, "Drone (carried in demo)", ["Pi 5 + Camera Module 3 Wide NoIR", "downward camera, 10-14 fps",
        "drops the nodes: SPACE =", "  'node dropped here'", "power bank, no cables"], "#fc6")
    box(4.3, 3.6, 2.6, 2.2, "Gateway", ["XIAO ESP32-S3 on USB", "ESP-NOW flooding mesh,", "no infrastructure",
        "JSON lines, 921600 baud"], "#6cf")
    box(8.0, 0.3, 3.0, 5.8, "Pi 5 field box", [":8080 camera mosaic", "  SIFT + RANSAC stitching", "  node drops -> positions",
        ":8000 fusion heatmap", "  energy model on 0.1 m grid", "  HAIL -> reply window", "  photo under the heat",
        ":8099 TAK overlay (KMZ)", "", "Wi-Fi hotspot T10-FIELD", "auto-start on boot"], "#f85")
    box(11.6, 3.4, 2.2, 2.7, "Responders", ["WinTAK / ATAK", "map overlay = mosaic", "T10 N1..N5 markers",
        "T10 LOOK HERE", "", "browser: heatmap"], "#c8f")
    box(11.6, 0.3, 2.2, 2.5, "Recordings", ["data/live_*.jsonl", "data/live_mosaic*", "-> replay + sim",
        "   when boards fail"], "#888")
    arrow((3.2, 4.7), (4.3, 4.7), "ESP-NOW", "#4c4", 0.22)
    arrow((6.9, 4.7), (8.0, 4.7), "USB", "#6cf", 0.22)
    arrow((3.2, 1.6), (8.0, 1.6), "camera frames + drop marks", "#fc6")
    arrow((11.0, 4.8), (11.6, 4.8), "CoT\n+KMZ", "#c8f", 0.3)
    arrow((11.0, 1.5), (11.6, 1.5), "", "#888")
    ax.text(7, 6.25, "Team 10: drop cheap acoustic nodes from a drone, map the rubble, show 'look here' in TAK",
            ha="center", color="#fff", fontsize=13, weight="bold")
    fig.savefig(out("diagrams/system_overview.png"), facecolor=fig.get_facecolor(), bbox_inches="tight")
    print("diagram")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", help="folder with the device photos / WinTAK screenshots (names in PHOTOS)")
    ap.add_argument("--skip-video", action="store_true")
    a = ap.parse_args()
    if a.photos:
        import_photos(a.photos)
    mosaics()
    diagram()
    synthetic()
    if not a.skip_video:
        build_video()


if __name__ == "__main__":
    main()
