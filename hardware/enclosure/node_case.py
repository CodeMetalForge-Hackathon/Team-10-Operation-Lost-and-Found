"""Parametric enclosure for a field node (Grove version):
XIAO ESP32-C5 + Grove Sound Sensor + Grove Vibration SW-420 + Grove Buzzer
+ 3.7 V LiPo + LED + antenna.  Generates STL files with manifold3d
(pip install manifold3d).

    python node_case.py   -> node_case_base.stl, node_case_lid.stl, node_case_plate.stl

All dimensions in mm.  Module sizes are NOMINAL values from retailer listings,
with slack added: measure your parts and edit PARAMETERS before printing.

Top view (interior), lid removed. All modules sit flat on the floor:

  +y  ┌──────────────────┬───────────┬───────────┐
      │  SW-420 (taped   │  Buzzer   │  LED hole │  rod-antenna hole in +y wall
      │  hard to floor)  │ (lid hole)│  wiring   │
      │                  ├── gap ────┤  bus      │  FPC antenna recess on +x wall
      │  LiPo bay        │  Sound    │  XIAO C5  │
      │                  │ (lid slot)│  USB-C ↓  │  USB-C slot in -y wall
  -y  └──────────────────┴───────────┴───────────┘
     -x                                          +x
Each module is located by four L-shaped corner fences, so its Grove connector can
face whichever way is convenient (gaps are left for plugs and cable bends).
Fix every module with double-sided foam tape; the SW-420 with hard tape or glue so
taps through the ground reach it.
"""
import struct
from pathlib import Path
import numpy as np
from manifold3d import Manifold, set_circular_segments

set_circular_segments(64)

# ---------------- PARAMETERS ----------------
WALL = 2.0          # side wall thickness
FLOOR = 1.6         # floor thickness
LID = 1.6           # lid plate thickness
CORNER_R = 3.0      # outer corner radius
CLEAR = 0.25        # lid-lip clearance per side (tune for your printer)
INNER_H = 13.5      # interior height, floor top -> lid underside (buzzer ~12 mm tall)
LIP_H, LIP_T = 2.0, 1.2
FENCE_H, FENCE_T, FENCE_LEG = 3.0, 1.2, 4.0

# Pocket sizes (x, y) = module outline + slack.  Measure!
LIPO_POCKET = (42.0, 28.0)      # 400 mAh 502535 (35x25x5) + protection board
SW420_POCKET = (42.0, 25.0)     # Grove SW-420, ~40 x 20 (some listings say 24) x 7
SOUND_POCKET = (22.0, 26.0)     # Grove Sound Sensor ~20 x 24 x 9.8, long side along y
BUZZER_POCKET = (22.0, 22.0)    # Grove Buzzer, 20 x 20
XIAO = (17.8, 21.0)             # XIAO footprint, rotated: USB-C edge faces -y wall
XIAO_RAIL_H, XIAO_PCB_T = 1.5, 1.0
PLUG_GAP = 8.0                  # room for a Grove plug + cable bend between modules

# Lid openings (positions are relative to the pocket's min corner)
MIC_SLOT_W, MIC_SLOT_L = 9.0, 14.0   # slot over the electret capsule: tolerates +/-2.5 mm
MIC_SLOT_CENTER = (11.0, 8.0)        # capsule assumed at the end AWAY from the connector
BUZZER_HOLE_D = 8.0                  # centred over the buzzer pocket
LED_HOLE_D = 5.2                     # 5 mm LED pushed up from below, glued
FPC_ANT = (38.0, 9.0, 0.6)           # stick-on FPC antenna recess (len, height, depth)
ROD_ANT_HOLE_D = 6.5                 # U.FL -> RP-SMA bulkhead / rod antenna; 0 = none

# ---------------- LAYOUT (interior coordinates) ----------------
M = 2.0                                            # margin to walls (clears the lid lip)
COL1_X = M
COL2_X = COL1_X + max(LIPO_POCKET[0], SW420_POCKET[0]) + PLUG_GAP
COL3_X = COL2_X + max(SOUND_POCKET[0], BUZZER_POCKET[0]) + 4.0
LIPO_Y = M
SW420_Y = LIPO_Y + LIPO_POCKET[1] + 4.0
SOUND_Y = M
BUZZER_Y = SOUND_Y + SOUND_POCKET[1] + PLUG_GAP + 2.0
IN_W = max(SW420_Y + SW420_POCKET[1], BUZZER_Y + BUZZER_POCKET[1]) + M
XIAO_X = COL3_X + 0.5
IN_L = XIAO_X + XIAO[0] + 0.5 + 1.5
OUT_L, OUT_W = IN_L + 2 * WALL, IN_W + 2 * WALL
BASE_H = FLOOR + INNER_H
XIAO_Y0 = 1.0                                       # USB-C overhangs ~1 mm toward -y wall
XIAO_XC = XIAO_X + XIAO[0] / 2
LED_POS = (XIAO_XC, IN_W - 10.0)


def box(x0, y0, z0, sx, sy, sz):
    return Manifold.cube([sx, sy, sz]).translate([x0, y0, z0])


def rounded_box(x0, y0, z0, sx, sy, sz, r):
    r = min(r, sx / 2 - 0.01, sy / 2 - 0.01)
    cyl = Manifold.cylinder(sz, r)
    pts = [(x0 + r, y0 + r), (x0 + sx - r, y0 + r), (x0 + r, y0 + sy - r), (x0 + sx - r, y0 + sy - r)]
    return Manifold.batch_hull([cyl.translate([px, py, z0]) for px, py in pts])


def slot(x, y, w, l, h, z0=0.0, along_y=True):
    """Stadium-shaped prism centred at (x, y)."""
    d = (l - w) / 2
    offs = [(0, -d), (0, d)] if along_y else [(-d, 0), (d, 0)]
    return Manifold.batch_hull([Manifold.cylinder(h, w / 2).translate([x + ox, y + oy, z0]) for ox, oy in offs])


def corner_fences(x0, y0, sx, sy):
    """Four L-shaped corner fences hugging a pocket from outside."""
    t, leg, h = FENCE_T, FENCE_LEG, FENCE_H

    def span(a, b):
        return min(a, b), abs(b - a)

    out = None
    for cx, ox in ((x0, -1), (x0 + sx, 1)):          # ox/oy: outward direction
        for cy, oy in ((y0, -1), (y0 + sy, 1)):
            bx, bw = span(cx - ox * leg, cx + ox * t)
            by, bh = span(cy, cy + oy * t)
            a = box(bx, by, 0, bw, bh, h)
            bx, bw = span(cx, cx + ox * t)
            by, bh = span(cy - oy * leg, cy + oy * t)
            a += box(bx, by, 0, bw, bh, h)
            out = a if out is None else out + a
    return out


def cyl_axis(d, length, start, axis):
    """Cylinder of diameter d along +x or +y starting at point `start`."""
    c = Manifold.cylinder(length, d / 2)
    c = c.rotate([0, 90, 0]) if axis == "x" else c.rotate([-90, 0, 0])
    return c.translate(list(start))


def make_base():
    outer = rounded_box(-WALL, -WALL, -FLOOR, OUT_L, OUT_W, BASE_H, CORNER_R)
    cavity = rounded_box(0, 0, 0, IN_L, IN_W, INNER_H + 1, max(CORNER_R - WALL, 0.5))
    base = outer - cavity

    for x0, y0, (sx, sy) in ((COL1_X, LIPO_Y, LIPO_POCKET), (COL1_X, SW420_Y, SW420_POCKET),
                             (COL2_X, SOUND_Y, SOUND_POCKET), (COL2_X, BUZZER_Y, BUZZER_POCKET)):
        base += corner_fences(x0, y0, sx, sy)

    # XIAO: rails along y under both long board edges + end stop; USB-C faces -y wall
    for x in (XIAO_X, XIAO_X + XIAO[0] - 1.5):
        base += box(x, XIAO_Y0 + 2, 0, 1.5, XIAO[1] - 2, XIAO_RAIL_H)
    base += box(XIAO_XC - 3, XIAO_Y0 + XIAO[1] + 0.2, 0, 6, 1.2, XIAO_RAIL_H + XIAO_PCB_T + 1.5)
    usb_zc = XIAO_RAIL_H + XIAO_PCB_T + 1.6
    base -= Manifold.batch_hull([cyl_axis(7.0, WALL + 2, (XIAO_XC + dx, -WALL - 1, usb_zc), "y")
                                 for dx in (-2.75, 2.75)])

    # FPC antenna recess on inside of +x wall (next to the XIAO, far from the LiPo)
    fl, fh, fd = FPC_ANT
    base -= box(IN_L - 0.01, (IN_W - fl) / 2, 0.8, fd + 0.01, fl, fh)

    # rod antenna / RP-SMA bulkhead hole in +y wall above the XIAO column
    if ROD_ANT_HOLE_D > 0:
        base -= cyl_axis(ROD_ANT_HOLE_D, WALL + 2, (XIAO_XC, IN_W - 1, INNER_H - LIP_H - ROD_ANT_HOLE_D / 2 - 1.0), "y")

    # pry notch on -x top edge
    base -= box(-WALL - 1, IN_W / 2 - 4, INNER_H - 1.2, WALL + 1.5, 8, 2)
    return base.translate([WALL, WALL, FLOOR])


def make_lid():
    # Printed top-face down: plate on the bed, lip pointing up. The lid is flipped onto
    # the base about the x axis, so every y position is mirrored (y -> IN_W - y).
    my = lambda y: IN_W - y
    plate = rounded_box(-WALL, -WALL, 0, OUT_L, OUT_W, LID, CORNER_R)
    lo = CLEAR
    lip = box(lo, lo, LID, IN_L - 2 * lo, IN_W - 2 * lo, LIP_H) - \
        box(lo + LIP_T, lo + LIP_T, LID - 1, IN_L - 2 * (lo + LIP_T), IN_W - 2 * (lo + LIP_T), LIP_H + 2)
    lid = plate + lip

    mx, myy = COL2_X + MIC_SLOT_CENTER[0], SOUND_Y + MIC_SLOT_CENTER[1]
    lid -= slot(mx, my(myy), MIC_SLOT_W, MIC_SLOT_L, LID + 2, -1)
    bx, by = COL2_X + BUZZER_POCKET[0] / 2, BUZZER_Y + BUZZER_POCKET[1] / 2
    lid -= Manifold.cylinder(LID + 2, BUZZER_HOLE_D / 2).translate([bx, my(by), -1])
    lid -= Manifold.cylinder(LID + 2, LED_HOLE_D / 2).translate([LED_POS[0], my(LED_POS[1]), -1])
    return lid.translate([WALL, WALL, 0])


def write_stl(m: Manifold, path: Path):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    t = np.asarray(mesh.tri_verts)
    tri = v[t]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    data = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    data["n"], data["v"] = n, tri
    with open(path, "wb") as f:
        f.write(struct.pack("<80sI", b"Team-10 node case (Grove)", len(t)))
        f.write(data.tobytes())


if __name__ == "__main__":
    out = Path(__file__).parent
    base, lid = make_base(), make_lid()
    plate = base + lid.translate([0, OUT_W + 6, 0])
    for name, m in (("base", base), ("lid", lid), ("plate", plate)):
        assert m.status().name == "NoError", m.status()
        write_stl(m, out / f"node_case_{name}.stl")
        b = m.bounding_box()
        print(f"node_case_{name}.stl  {b[3]-b[0]:.1f} x {b[4]-b[1]:.1f} x {b[5]-b[2]:.1f} mm  "
              f"vol {m.volume()/1000:.1f} cm3  genus {m.genus()}")
