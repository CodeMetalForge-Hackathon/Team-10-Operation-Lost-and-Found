"""make_concept_gifs.py: animated views of the drone deployment concept (hardware/drone_concept).

  python tools/make_concept_gifs.py        # -> media/gifs/drone_concept_turntable.gif, drone_concept_drop.gif
                                           #    + media/video/drone_concept_turntable.mp4
Needs: trimesh manifold3d pycollada numpy scipy pyvista pillow opencv-python (first run downloads the PX4 meshes).
Builds the model with build_concept.py, then renders off-screen with PyVista (same colours and lights as its renders).
"""
import math
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hardware", "drone_concept"))
import build_concept as bc  # noqa: E402
import pyvista as pv  # noqa: E402

GIFS = os.path.join(ROOT, "media", "gifs")
VIDEO = os.path.join(ROOT, "media", "video")


def plotter(size):
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background("#eef1f5", top="#ffffff")
    p.add_light(pv.Light(position=(600, -800, 1200), focal_point=(0, 0, 0), intensity=0.9))
    p.add_light(pv.Light(position=(-900, 600, 400), focal_point=(0, 0, 0), intensity=0.45))
    p.add_light(pv.Light(position=(200, 300, -900), focal_point=(0, 0, 0), intensity=0.35))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    p.enable_anti_aliasing("ssaa")
    return p


def add_mesh(p, mesh, colorkey, name, opacity=None):
    if opacity is None:
        opacity = 0.35 if colorkey == "mag_housing" and name != "mag_floor" else 1.0
    smooth = name.startswith("node_") or "bell" in name or "motor" in name
    return p.add_mesh(pv.wrap(mesh), color=np.array(bc.COLORS[colorkey]) / 255.0, opacity=opacity,
                      smooth_shading=smooth, specular=0.35, specular_power=20, ambient=0.18, diffuse=0.85)


def frame(p):
    p.render()  # off-screen plotters don't redraw on their own after camera or actor changes
    return Image.fromarray(p.screenshot(return_img=True))


def save_gif(frames, path, ms, colors=160):
    pal = [f.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=ms, loop=0, optimize=True)
    print(f"{path}  {len(frames)} frames  {os.path.getsize(path) / 1e6:.1f} MB")


def save_mp4(frames, path, fps):
    import cv2
    h, w = frames[0].size[1], frames[0].size[0]
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"avc1"), fps, (w, h))  # H.264 (plays in browsers)
    if not out.isOpened():  # no OpenH264 on this machine: MPEG-4 part 2 still plays in desktop players
        out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        out.write(cv2.cvtColor(np.array(f.convert("RGB")), cv2.COLOR_RGB2BGR))
    out.release()
    print(f"{path}  {os.path.getsize(path) / 1e6:.1f} MB")


def turntable(model, n=60, size=(960, 680)):
    p = plotter(size)
    for _g, name, c, m in model.items:
        add_mesh(p, m, c, name)
    focal, r, elev = (0, 0, -40), 1080, math.radians(24)
    frames = []
    for k in range(n):
        az = math.radians(-50 + 360 * k / n)
        pos = (r * math.cos(elev) * math.cos(az), r * math.cos(elev) * math.sin(az), focal[2] + r * math.sin(elev))
        p.camera_position = [pos, focal, (0, 0, 1)]
        frames.append(frame(p))
    p.close()
    return frames


def drop_sequence(model, node_parts, size=(960, 680)):
    """Node 0 (over the floor hole) falls out; the rotor then steps 60 deg to bring the next node over the hole."""
    p = plotter(size)
    spinning = []  # actors that turn with the rotor: the rotor and the loaded nodes
    for g, name, c, m in model.items:
        if g == "dropped":
            continue  # node 0 is animated below
        a = add_mesh(p, m, c, name)
        if name == "mag_rotor" or g == "nodes":
            spinning.append(a)
    shell, band, led = node_parts
    node0 = [add_mesh(p, mesh, c, "node_0_" + c) for mesh, c in ((shell, "node"), (band, "node_band"), (led, "node_led"))]
    a0 = bc.mag_angles()[0]
    x0, y0 = bc.polar(bc.PITCH_R, a0)
    floor_top = bc.MAG_TOP - bc.MAG_H + 3
    z_seat = floor_top + bc.NODE_D / 2 + 0.5
    fall = 330.0
    p.camera_position = [(-820, -640, 60), (-30, 0, -215), (0, 0, 1)]  # aft side: the floor hole faces aft

    def place_node0(dz, spin_deg, visible=True):
        tf = bc.T(x0, y0, z_seat - dz) @ bc.Rz(a0 + spin_deg) @ bc.Rx(spin_deg * 0.6)
        for a in node0:
            a.user_matrix = tf
            a.SetVisibility(visible)

    def turn(deg):
        for a in spinning:
            a.user_matrix = bc.Rz(deg)

    frames = []
    for _ in range(6):                                   # loaded, node 0 over the hole
        place_node0(0, 0); turn(0); frames.append(frame(p))
    for k in range(1, 15):                               # free fall
        t = k / 14
        place_node0(fall * t * t, 160 * t); turn(0); frames.append(frame(p))
    place_node0(0, 0, visible=False)
    for _ in range(4):
        frames.append(frame(p))
    for k in range(1, 13):                               # rotor steps 60 deg (eased): next node arrives over the hole
        t = k / 12
        turn(-60 * (0.5 - 0.5 * math.cos(math.pi * t))); frames.append(frame(p))
    for _ in range(8):
        frames.append(frame(p))
    p.close()
    return frames


def main():
    os.makedirs(GIFS, exist_ok=True)
    os.makedirs(VIDEO, exist_ok=True)
    model = bc.Model()
    bc.add_airframe(model)
    bc.add_top_deck(model)
    bc.add_underside(model)
    node_parts = bc.add_dispenser(model)

    tt = turntable(model)
    save_gif([f.resize((720, 510), Image.LANCZOS) for f in tt], os.path.join(GIFS, "drone_concept_turntable.gif"), 70)
    save_mp4(tt, os.path.join(VIDEO, "drone_concept_turntable.mp4"), 15)
    drop = drop_sequence(model, node_parts)
    save_gif([f.resize((720, 510), Image.LANCZOS) for f in drop], os.path.join(GIFS, "drone_concept_drop.gif"), 80)


if __name__ == "__main__":
    main()
