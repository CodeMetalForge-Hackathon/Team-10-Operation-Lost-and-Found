"""Concept model: COTS quadcopter carrying a one-by-one sphere-node dispenser.

Base airframe: Holybro X500 meshes from PX4-gazebo-models (BSD-3-Clause, see
vendor/LICENSE_PX4). They are downloaded into vendor/ on first run and placed using
the poses in PX4's model.sdf. Everything else is modelled here from primitives:

  * top accessory deck: Raspberry Pi 5 + active cooler, small ESP32-S3 board,
    5 V battery pack, power/USB leads;
  * Pi camera, nadir-facing, under the nose (architecture: overhead LED spotting);
  * under the frame: flight LiPo on the rails, then a 6-chamber revolver
    magazine. An N20 gear motor in the hub steps the rotor 60 deg; the chamber
    over the floor hole drops exactly one node. 5 loaded, 1 shown mid-drop.
  * sensor node: 40 mm high-vis sphere with seam band, mic port, buzzer vents.

Concept only: not a printable, load-checked design. Units in the output: mm.

Run:  python hardware/drone_concept/build_concept.py
Needs: trimesh manifold3d pycollada numpy scipy pyvista (pyvista only for renders).
"""

import math
import os
import sys
import urllib.request

import numpy as np
import trimesh
from trimesh import creation as C
from trimesh.transformations import rotation_matrix, translation_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor")
PARTS = os.path.join(HERE, "parts")
RENDERS = os.path.join(HERE, "renders")
PX4 = "https://raw.githubusercontent.com/PX4/PX4-gazebo-models/main/"
PX4_FILES = {
    "NXP-HGD-CF.dae": "models/x500_base/meshes/NXP-HGD-CF.dae",
    "5010Base.dae": "models/x500_base/meshes/5010Base.dae",
    "5010Bell.dae": "models/x500_base/meshes/5010Bell.dae",
    "1345_prop_ccw.stl": "models/x500_base/meshes/1345_prop_ccw.stl",
    "1345_prop_cw.stl": "models/x500_base/meshes/1345_prop_cw.stl",
    "LICENSE_PX4": "LICENSE",
}

NODE_D = 40.0          # sensor node sphere diameter, mm
CHAMBERS = 6
PITCH_R = 45.0         # chamber centre radius in the magazine
MAG_R = 69.0           # magazine outer radius: X500 legs come to 72-75 mm at its top
MAG_TOP = -84.0        # magazine top face, base_link z (mm)
MAG_H = 58.0           # magazine total height incl. plates
DROP_ANGLE = 180.0     # floor hole faces aft (camera is at the nose)

COLORS = {
    "carbon": (40, 40, 44), "metal": (175, 178, 185), "rubber": (25, 25, 25),
    "foam": (60, 60, 60), "fmu": (30, 60, 140), "plastic": (55, 55, 60),
    "motor": (150, 150, 158), "bell": (200, 70, 40), "prop": (20, 20, 22),
    "deck": (35, 35, 38), "standoff": (190, 160, 60),
    "pcb_green": (20, 110, 60), "pi_metal": (200, 200, 205), "cooler": (120, 125, 135),
    "fan": (30, 30, 30), "connector": (25, 25, 25), "esp_pcb": (20, 20, 25),
    "esp_can": (190, 190, 195), "antenna": (230, 230, 230),
    "battery": (30, 90, 200), "battery_label": (250, 200, 20), "strap": (15, 15, 15),
    "lipo": (60, 60, 70), "lipo_label": (200, 30, 30),
    "wire_red": (200, 30, 30), "wire_black": (20, 20, 20), "ribbon": (230, 220, 180),
    "camera_pcb": (20, 110, 60), "lens": (10, 10, 10),
    "mag_housing": (200, 205, 210), "mag_rotor": (70, 75, 85), "mag_motor": (150, 150, 160),
    "node": (255, 110, 0), "node_band": (30, 30, 30), "node_led": (240, 255, 240),
}


# ------------------------------------------------------------------ helpers
def T(x=0.0, y=0.0, z=0.0):
    return translation_matrix([x, y, z])


def Rz(deg):
    return rotation_matrix(math.radians(deg), [0, 0, 1])


def Rx(deg):
    return rotation_matrix(math.radians(deg), [1, 0, 0])


def Ry(deg):
    return rotation_matrix(math.radians(deg), [0, 1, 0])


def box(sx, sy, sz, x=0, y=0, z=0):
    """Box with its bottom face at z (more natural for stacking parts)."""
    return C.box([sx, sy, sz], transform=T(x, y, z + sz / 2))


def cyl(r, h, x=0, y=0, z=0, sections=48):
    """Vertical cylinder, bottom face at z."""
    return C.cylinder(radius=r, height=h, sections=sections, transform=T(x, y, z + h / 2))


def rounded_plate(sx, sy, t, r, x=0, y=0, z=0):
    parts = [box(sx - 2 * r, sy, t, x, y, z), box(sx, sy - 2 * r, t, x, y, z)]
    for cx in (-1, 1):
        for cy in (-1, 1):
            parts.append(cyl(r, t, x + cx * (sx / 2 - r), y + cy * (sy / 2 - r), z, 24))
    return union(parts)


def union(meshes):
    return trimesh.boolean.union(meshes, engine="manifold")


def diff(a, b):
    return trimesh.boolean.difference([a] + (b if isinstance(b, list) else [b]), engine="manifold")


def wire(points, r):
    """A cable through a polyline (cylinders + joint spheres)."""
    pts = [np.array(p, float) for p in points]
    parts = []
    for a, b in zip(pts[:-1], pts[1:]):
        parts.append(C.cylinder(radius=r, segment=[a, b], sections=16))
    for p in pts[1:-1]:
        parts.append(C.icosphere(subdivisions=1, radius=r).apply_translation(p))
    return trimesh.util.concatenate(parts)


def ribbon(points, w, t):
    """A flat ribbon cable through a polyline in the x-z plane (width along y)."""
    parts = []
    for a, b in zip(points[:-1], points[1:]):
        a, b = np.array(a, float), np.array(b, float)
        d = b - a
        L = np.linalg.norm(d)
        m = C.box([L, w, t])
        ang = math.atan2(d[2], d[0])
        m.apply_transform(rotation_matrix(-ang, [0, 1, 0]))
        m.apply_translation((a + b) / 2)
        parts.append(m)
    return trimesh.util.concatenate(parts)


class Model:
    def __init__(self):
        self.items = []  # (group, name, colorkey, mesh)

    def add(self, group, name, color, mesh, tf=None):
        if tf is not None:
            mesh = mesh.copy().apply_transform(tf)
        self.items.append((group, name, color, mesh))

    def group(self, g):
        return [m for gg, _, _, m in self.items if gg == g]


# ------------------------------------------------------------------ airframe
def fetch_px4():
    os.makedirs(VENDOR, exist_ok=True)
    for name, path in PX4_FILES.items():
        dst = os.path.join(VENDOR, name)
        if not os.path.exists(dst):
            print("downloading", path)
            urllib.request.urlretrieve(PX4 + path, dst)


def load_dae_parts(path):
    scene = trimesh.load(path)
    out = []
    for node in scene.graph.nodes_geometry:
        tf, gname = scene.graph[node]
        out.append((gname, scene.geometry[gname].copy().apply_transform(tf)))
    return out


FRAME_COLOR = {
    "CarbonFiber": "carbon", "Metal": "metal", "LandingFoam": "foam",
    "LandingRubber": "rubber", "RailsRubber": "rubber", "FMUK66": "fmu",
    "RailsAntennaHolder": "plastic", "LandingPlastic": "plastic", "FMURubber": "rubber",
}

M = 1000.0  # PX4 meshes are in metres


def add_airframe(model):
    fetch_px4()
    # model.sdf: base_link visual pose 0 0 .025, yaw pi
    frame_tf = T(0, 0, 25) @ Rz(180) @ np.diag([M, M, M, 1])
    for gname, mesh in load_dae_parts(os.path.join(VENDOR, "NXP-HGD-CF.dae")):
        key = gname.replace("-mesh", "")
        model.add("airframe", "x500_" + key, FRAME_COLOR.get(key, "carbon"), mesh, frame_tf)

    base = trimesh.load(os.path.join(VENDOR, "5010Base.dae"), force="mesh")
    bell = trimesh.load(os.path.join(VENDOR, "5010Bell.dae"), force="mesh")
    props = {d: trimesh.load(os.path.join(VENDOR, "1345_prop_%s.stl" % d)) for d in ("ccw", "cw")}
    s = 0.8461538461538461
    rotors = [((174, -174), "ccw", 20), ((-174, 174), "ccw", 70), ((174, 174), "cw", 115), ((-174, -174), "cw", 160)]
    for i, ((x, y), d, spin) in enumerate(rotors):
        model.add("airframe", "motor_base_%d" % i, "motor", base,
                  T(x, y, 32) @ Rz(math.degrees(-0.45)) @ np.diag([M, M, M, 1]))
        link = T(x, y, 60)
        model.add("airframe", "motor_bell_%d" % i, "bell", bell, link @ T(0, 0, -32) @ np.diag([M, M, M, 1]))
        prop_tf = link @ Rz(spin) @ T(-22, -146.38461538461536, -16) @ np.diag([s * M, s * M, s * M, 1])
        model.add("props", "prop_%d" % i, "prop", props[d], prop_tf)


# ------------------------------------------------------------------ top deck
DECK_Z = 68.0  # bottom of the accessory deck plate


def add_top_deck(model):
    g = "topdeck"
    plate = rounded_plate(150, 100, 2, 8, z=DECK_Z)
    # lightening slots
    slots = [C.box([40, 10, 6], transform=T(x, y, DECK_Z + 1)) for x in (-45, 0, 45) for y in (-34, 34)]
    plate = diff(plate, slots)
    model.add(g, "deck_plate", "deck", plate)
    for x in (-62, 62):
        for y in (-40, 40):
            model.add(g, "deck_standoff", "standoff", C.cylinder(radius=2.8, height=34, sections=6,
                                                             transform=T(x, y, 34 + 17)))

    # Raspberry Pi 5 (85 x 56), ports to the rear (-x)
    px, py, pz = -20.0, -19.0, DECK_Z + 2 + 5  # on 5 mm standoffs
    for dx in (-29, 29):
        for dy in (-24.5, 24.5):
            model.add(g, "pi_standoff", "standoff", cyl(1.6, 5, px + dx + 3.5, py + dy, DECK_Z + 2, 6))
    model.add(g, "pi5_pcb", "pcb_green", rounded_plate(85, 56, 1.6, 3, px, py, pz))
    top = pz + 1.6
    model.add(g, "pi5_ethernet", "pi_metal", box(21, 16, 13.5, px - 42.5 + 10, py + 17, top))
    model.add(g, "pi5_usb_a", "pi_metal", box(17.5, 13.5, 16, px - 42.5 + 8.5, py - 1, top))
    model.add(g, "pi5_usb_b", "pi_metal", box(17.5, 13.5, 16, px - 42.5 + 8.5, py - 19, top))
    model.add(g, "pi5_gpio", "connector", box(51, 5, 8.5, px + 6, py + 24.5, top))
    model.add(g, "pi5_usbc", "pi_metal", box(9, 7.5, 3.2, px + 31, py - 26, top))
    for k in range(2):
        model.add(g, "pi5_hdmi", "pi_metal", box(7.5, 6.5, 3.2, px + 12 + 13.5 * k, py - 25.5, top))
    model.add(g, "pi5_cam_conn", "connector", box(3, 18, 4, px + 36, py, top))
    # active cooler: finned block + fan
    cz = top + 2
    model.add(g, "cooler_base", "cooler", box(54, 40, 2.5, px + 10, py + 2, cz))
    for k in range(12):
        model.add(g, "cooler_fin", "cooler", box(54, 1.2, 6, px + 10, py - 16 + 3.2 * k, cz + 2.5))
    model.add(g, "cooler_fan", "fan", cyl(14.5, 6.5, px + 20, py + 2, cz + 2.5))
    model.add(g, "cooler_fan_hub", "cooler", cyl(5.5, 7, px + 20, py + 2, cz + 2.5))

    # small ESP32-S3 board (mesh radio bridge), front-right of the Pi
    ex, ey, ez = 46.0, -22.0, DECK_Z + 2 + 3
    for dx in (-10, 10):
        model.add(g, "esp_standoff", "standoff", cyl(1.2, 3, ex + dx, ey, DECK_Z + 2, 6))
    model.add(g, "esp32_pcb", "esp_pcb", box(25.5, 18, 1.2, ex, ey, ez))
    model.add(g, "esp32_can", "esp_can", box(13, 15, 2.6, ex + 3, ey, ez + 1.2))
    model.add(g, "esp32_usbc", "pi_metal", box(7.5, 9, 3.2, ex - 10, ey, ez + 1.2))
    model.add(g, "esp32_antenna_base", "connector", cyl(2.2, 6, ex + 11, ey + 6, ez + 1.2, 16))
    model.add(g, "esp32_antenna", "antenna", cyl(1.6, 38, ex + 11, ey + 6, ez + 7, 16))

    # 5 V battery pack (powers Pi + ESP32), left side of the deck
    bx, by, bz = -12.0, 30.0, DECK_Z + 2
    model.add(g, "battery_pack", "battery", rounded_plate(72, 36, 18, 4, bx, by, bz))
    model.add(g, "battery_label", "battery_label", box(40, 36.4, 8, bx + 5, by, bz + 5))
    for sx in (-20, 20):  # velcro straps through the deck
        model.add(g, "battery_strap", "strap", box(12, 38, 18.8, bx + sx, by, bz - 0.4))

    # leads: battery -> Pi USB-C (power), Pi USB-A -> ESP32 USB-C
    model.add(g, "lead_power", "wire_red", wire([(bx + 36, by - 6, bz + 9), (bx + 50, by - 20, bz + 10),
                                                  (px + 42, py - 35, top + 2), (px + 35.5, py - 26, top + 1.6)], 1.8))
    # Pi GPIO UART (TX, RX, GND) -> ESP32 bridge, short jumper wires
    for k, col in enumerate(("wire_red", "battery_label", "wire_black")):
        hx = px + 6 + 14 + 2.5 * k
        model.add(g, "uart_jumper_%d" % k, col, wire([(hx, py + 24.5, top + 8.5), (hx + 4, py + 30, top + 16),
                                                       (ex - 8 + 2.5 * k, ey + 16, ez + 10),
                                                       (ex - 8 + 2.5 * k, ey + 8, ez + 1.2)], 0.7))


# ------------------------------------------------------------------ camera + flight battery
def add_underside(model):
    g = "underside"
    # flight LiPo (4S 5200 mAh class) strapped on the rails
    model.add(g, "flight_lipo", "lipo", rounded_plate(150, 46, 36, 4, 15, 0, -64))
    model.add(g, "flight_lipo_label", "lipo_label", box(80, 46.4, 20, 10, 0, -56))
    for sx in (-30, 50):
        model.add(g, "lipo_strap", "strap", box(20, 47, 37, 15 + sx, 0, -64.5))
    # Pi camera module 3, nadir, under the nose
    cx = 152.0
    model.add(g, "cam_bracket", "deck", box(30, 30, 2, cx, 0, -12))
    model.add(g, "cam_drop", "deck", box(2, 30, 16, cx - 14, 0, -26))
    model.add(g, "cam_pcb", "camera_pcb", box(25, 24, 1, cx, 0, -27))
    model.add(g, "cam_body", "connector", box(8.5, 8.5, 4, cx, 0, -31))
    model.add(g, "cam_lens", "lens", cyl(3.2, 2.5, cx, 0, -33.5))
    model.add(g, "cam_ribbon", "ribbon", ribbon([(cx - 12, 0, -26.5), (cx - 20, 0, -20), (cx - 30, 0, 20),
                                                  (55, 0, DECK_Z + 3), (16.5, 0, DECK_Z + 12)], 16, 0.4))


# ------------------------------------------------------------------ dispenser
def mag_angles():
    return [DROP_ANGLE + 360.0 * k / CHAMBERS for k in range(CHAMBERS)]


def polar(r, deg):
    return r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg))


def build_node():
    """40 mm sensor node shell: sphere, seam band, mic port, buzzer vents, LED window."""
    r = NODE_D / 2
    shell = C.icosphere(subdivisions=4, radius=r)
    cutters = [cyl(2.2, 6, 0, 0, r - 3, 24)]  # mic port, top
    for k in range(6):  # buzzer vent ring
        x, y = polar(9, 60 * k)
        c = cyl(1.1, 8, 0, 0, 0, 12)
        c.apply_transform(T(0, 0, -4))
        tilt = rotation_matrix(math.atan2(9, r), [-math.sin(math.radians(60 * k)), math.cos(math.radians(60 * k)), 0])
        c.apply_transform(tilt)
        c.apply_translation([x, y, math.sqrt(r * r - 81)])
        cutters.append(c)
    shell = diff(shell, cutters)
    band = C.annulus(r_min=r - 1.0, r_max=r + 0.8, height=3.0, sections=96)
    led = C.cylinder(radius=3.0, height=3, sections=24, transform=T(r - 0.5, 0, 6) @ Ry(90))
    return shell, band, led


def add_dispenser(model):
    g = "dispenser"
    top = MAG_TOP
    bot = MAG_TOP - MAG_H
    floor_top = bot + 3
    # stationary housing: top plate, wall with viewing windows, floor with the drop hole
    model.add(g, "mag_top_plate", "mag_housing", cyl(MAG_R, 3, z=top - 3, sections=96))
    wall = C.annulus(r_min=MAG_R - 3, r_max=MAG_R, height=MAG_H - 6, sections=96,
                     transform=T(0, 0, bot + 3 + (MAG_H - 6) / 2))
    windows = []
    for a in mag_angles():
        x, y = polar(MAG_R - 1.5, a)
        windows.append(C.box([10, 22, 26], transform=T(x, y, floor_top + NODE_D / 2 + 0.5) @ Rz(a)))
    model.add(g, "mag_wall", "mag_housing", diff(wall, windows))
    hx, hy = polar(PITCH_R, DROP_ANGLE)
    floor = diff(cyl(MAG_R, 3, z=bot, sections=96), cyl(NODE_D / 2 + 2.5, 10, hx, hy, bot - 3, 48))
    model.add(g, "mag_floor", "mag_housing", floor)
    model.add(g, "mag_drop_lip", "mag_housing",
              C.annulus(r_min=NODE_D / 2 + 2.5, r_max=NODE_D / 2 + 5, height=6, sections=48,
                        transform=T(hx, hy, bot - 3)))
    # rotor: hub (houses N20 gear motor) + 6 fins between chambers; rides on the floor
    rot_h = MAG_H - 6 - 2
    rotor = [cyl(18, rot_h, z=floor_top + 0.5, sections=48)]
    for a in mag_angles():
        fa = a + 180.0 / CHAMBERS
        x, y = polar((18 + MAG_R - 4) / 2, fa)
        rotor.append(C.box([MAG_R - 4 - 18 + 2, 3, rot_h], transform=T(x, y, floor_top + 0.5 + rot_h / 2) @ Rz(fa)))
    model.add(g, "mag_rotor", "mag_rotor", union(rotor))
    model.add(g, "mag_motor_cap", "mag_motor", cyl(11, 8, z=top, sections=32))
    model.add(g, "mag_index_sensor", "connector", box(10, 6, 5, *polar(MAG_R - 14, DROP_ANGLE + 30), top))
    # hangers to the rails, clear of the flight LiPo
    for x in (-60, 60):
        for y in (-34, 34):
            model.add(g, "mag_hanger", "standoff", cyl(3, -30 - top, x, y, top, 6))
            model.add(g, "mag_rail_clamp", "plastic", box(14, 12, 8, x, y, -30))
    model.add(g, "mag_lead", "wire_black", wire([(0, 10, top + 8), (0, 30, top + 20), (-70, 40, -40),
                                                 (-80, 45, 20), (-55, 40, DECK_Z + 4)], 1.5))

    # nodes: 5 loaded, the one over the hole is mid-drop
    shell, band, led = build_node()
    cz = floor_top + NODE_D / 2 + 0.5
    for k, a in enumerate(mag_angles()):
        x, y = polar(PITCH_R, a)
        if k == 0:
            tf = T(x, y, bot - 30) @ Rz(25) @ Rx(18)
            grp = "dropped"
        else:
            tf = T(x, y, cz) @ Rz(a)
            grp = "nodes"
        model.add(grp, "node_%d_shell" % k, "node", shell, tf)
        model.add(grp, "node_%d_band" % k, "node_band", band, tf)
        model.add(grp, "node_%d_led" % k, "node_led", led, tf)
    return shell, band, led


# ------------------------------------------------------------------ export
def export(model, node_parts):
    os.makedirs(PARTS, exist_ok=True)
    allm = trimesh.util.concatenate([m for _, _, _, m in model.items])
    allm.export(os.path.join(HERE, "drone_concept_assembly.stl"))

    groups = sorted({g for g, _, _, _ in model.items})
    for g in groups:
        trimesh.util.concatenate(model.group(g)).export(os.path.join(PARTS, "%s.stl" % g))
    # printable parts on their own, at the origin
    for name in ("mag_top_plate", "mag_wall", "mag_floor", "mag_rotor", "deck_plate"):
        m = next(mm for _, n, _, mm in model.items if n == name).copy()
        m.apply_translation(-m.bounds[0] * [0, 0, 1] - [0, 0, 0])
        m.export(os.path.join(PARTS, "print_%s.stl" % name))
    shell, band, led = node_parts
    trimesh.util.concatenate([shell, band, led]).export(os.path.join(PARTS, "sensor_node_sphere.stl"))

    # coloured scene for viewers (Windows 3D Viewer, VS Code glTF preview, Blender)
    scene = trimesh.Scene()
    for i, (g, n, c, m) in enumerate(model.items):
        mm = m.copy()
        mm.visual = trimesh.visual.ColorVisuals(mm, face_colors=list(COLORS[c]) + [255])
        scene.add_geometry(mm, node_name="%s_%s_%d" % (g, n, i))
    scene.export(os.path.join(HERE, "drone_concept_assembly.glb"))

    b = allm.bounds
    print("assembly: %d faces, bounds mm x[%.0f, %.0f] y[%.0f, %.0f] z[%.0f, %.0f]"
          % (len(allm.faces), b[0][0], b[1][0], b[0][1], b[1][1], b[0][2], b[1][2]))


# ------------------------------------------------------------------ render
def render(model):
    import pyvista as pv

    os.makedirs(RENDERS, exist_ok=True)

    def plotter():
        p = pv.Plotter(off_screen=True, window_size=(1800, 1300), lighting="none")
        p.set_background("#eef1f5", top="#ffffff")
        p.add_light(pv.Light(position=(600, -800, 1200), focal_point=(0, 0, 0), intensity=0.9))
        p.add_light(pv.Light(position=(-900, 600, 400), focal_point=(0, 0, 0), intensity=0.45))
        p.add_light(pv.Light(position=(200, 300, -900), focal_point=(0, 0, 0), intensity=0.35))
        p.add_light(pv.Light(light_type="headlight", intensity=0.25))
        p.enable_anti_aliasing("ssaa")
        return p

    def add(p, offsets=None, skip=(), housing_opacity=0.35, ghost_airframe=False):
        for g, n, c, m in model.items:
            if g in skip or n in skip:
                continue
            mesh = m.copy()
            if offsets and g in offsets:
                mesh.apply_translation(offsets[g])
            pm = pv.wrap(mesh)
            opacity = 1.0
            if c == "mag_housing" and n != "mag_floor":
                opacity = housing_opacity
            if ghost_airframe and g in ("airframe", "props", "underside"):
                opacity = 0.18
            smooth = n.startswith("node_") or "bell" in n or "motor" in n
            p.add_mesh(pm, color=np.array(COLORS[c]) / 255.0, opacity=opacity, smooth_shading=smooth,
                       specular=0.35, specular_power=20, ambient=0.18, diffuse=0.85)

    views = {
        "01_iso_front": ((720, -620, 430), (0, 0, -40)),
        "02_iso_rear_low": ((-650, 560, -160), (0, 0, -60)),
        "03_side": ((0, -1000, -20), (0, 0, -60)),
        "04_top": ((0, 0, 1100), (0, 0, 0)),
        "05_underside": ((300, -250, -900), (0, 0, -100)),
    }
    for name, (pos, foc) in views.items():
        p = plotter()
        add(p)
        up = (1, 0, 0) if name == "04_top" else (0, 0, 1)
        p.camera_position = [pos, foc, up]
        p.camera.zoom(1.0)
        p.screenshot(os.path.join(RENDERS, name + ".png"))
        p.close()

    # close-ups
    p = plotter()
    add(p, skip=("airframe", "props", "topdeck"), housing_opacity=0.15)
    p.camera_position = [(330, -300, -20), (0, 0, -125), (0, 0, 1)]
    p.screenshot(os.path.join(RENDERS, "06_dispenser_closeup.png"))
    p.close()

    p = plotter()
    add(p, skip=("props", "dispenser", "nodes", "dropped", "underside"))
    p.camera_position = [(260, -230, 260), (-5, 0, 75), (0, 0, 1)]
    p.screenshot(os.path.join(RENDERS, "07_top_deck_closeup.png"))
    p.close()

    p = plotter()
    off = {"props": (0, 0, 140), "topdeck": (0, 0, 90), "underside": (0, 0, -40),
           "dispenser": (0, 0, -150), "nodes": (0, 0, -150), "dropped": (0, 0, -250)}
    add(p, offsets=off)
    p.camera_position = [(950, -820, 260), (0, 0, -90), (0, 0, 1)]
    p.screenshot(os.path.join(RENDERS, "08_exploded.png"))
    p.close()


def main():
    model = Model()
    add_airframe(model)
    add_top_deck(model)
    add_underside(model)
    node_parts = add_dispenser(model)
    export(model, node_parts)
    if "--no-render" not in sys.argv:
        render(model)
        print("renders in", RENDERS)


if __name__ == "__main__":
    main()
