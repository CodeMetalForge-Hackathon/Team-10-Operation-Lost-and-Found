"""Parametric enclosure for a field node: XIAO ESP32-C5 + Adafruit ICS-43434 mic
+ 3.7 V LiPo + antenna.  Generates STL files with manifold3d (pip install manifold3d).

    python node_case.py          -> node_case_base.stl, node_case_lid.stl, node_case_plate.stl

All dimensions in mm.  Part sizes below are ASSUMED nominal values: measure your
actual parts with calipers and edit the PARAMETERS block before printing.

Layout (top view, lid removed):           Z
  +y wall: FPC antenna recess              ^
  +-------------------------------+        |  lid (mic port + gasket ring)
  | XIAO C5 (USB-C -> -x wall) MIC |       |  12 mm interior height
  +-----------divider-------------+        |  floor
  |        LiPo battery bay       |
  +-------------------------------+  -x wall also has an optional rod-antenna hole
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

# Parts (nominal, with some slack added below)
LIPO = (40.0, 27.0, 6.0)        # 400 mAh 502535 (35x25x5) + protection board + slack
XIAO = (21.0, 17.8)             # Seeed XIAO footprint
XIAO_RAIL_H = 1.5               # board sits on rails, room for BAT+/- wires underneath
XIAO_PCB_T = 1.0
MIC = (12.7, 17.8)              # Adafruit ICS-43434 breakout (x, y) - MEASURE
MIC_STACK_T = 2.6               # PCB + mic package (breakout flipped, port facing lid)
MIC_PORT_D = 2.5                # sound hole in lid
MIC_PORT_OFFSET = (0.0, 0.0)    # port position relative to breakout centre - MEASURE
FPC_ANT = (38.0, 9.5, 0.6)      # recess for stick-on FPC antenna (len, height, depth)
ROD_ANT_HOLE_D = 6.5            # hole for U.FL->RP-SMA bulkhead / rod antenna; 0 = none

INNER_H = 12.0                  # interior height (floor top -> lid underside)
LIP_H = 2.0
LIP_T = 1.2
DIVIDER_T = 1.2
DIVIDER_H = 5.0

# ---------------- DERIVED LAYOUT ----------------
ELEC_W = max(XIAO[1], MIC[1]) + 2.4
IN_L = max(LIPO[0], 1.0 + XIAO[0] + 4.0 + MIC[0] + 2.0) + 2.0
IN_W = LIPO[1] + DIVIDER_T + ELEC_W
OUT_L, OUT_W = IN_L + 2 * WALL, IN_W + 2 * WALL
BASE_H = FLOOR + INNER_H

ELEC_Y0 = LIPO[1] + DIVIDER_T          # interior y where electronics strip starts
ELEC_YC = ELEC_Y0 + ELEC_W / 2
XIAO_X0 = 1.0                           # gap for USB-C overhang against -x wall
MIC_X0 = XIAO_X0 + XIAO[0] + 4.0
MIC_XC = MIC_X0 + MIC[0] / 2


def box(x0, y0, z0, sx, sy, sz):
    return Manifold.cube([sx, sy, sz]).translate([x0, y0, z0])


def rounded_box(x0, y0, z0, sx, sy, sz, r):
    r = min(r, sx / 2 - 0.01, sy / 2 - 0.01)
    if r <= 0:
        return box(x0, y0, z0, sx, sy, sz)
    cyl = Manifold.cylinder(sz, r)
    pts = [(x0 + r, y0 + r), (x0 + sx - r, y0 + r), (x0 + r, y0 + sy - r), (x0 + sx - r, y0 + sy - r)]
    return Manifold.batch_hull([cyl.translate([px, py, z0]) for px, py in pts])


def cyl_x(d, length, x0, y, z):
    """Cylinder along +x starting at x0."""
    return Manifold.cylinder(length, d / 2).rotate([0, 90, 0]).translate([x0, y, z])


# Interior coordinates: (0,0,0) = inner corner on top of floor. Shift to world at the end.
def make_base():
    outer = rounded_box(-WALL, -WALL, -FLOOR, OUT_L, OUT_W, BASE_H, CORNER_R)
    cavity = rounded_box(0, 0, 0, IN_L, IN_W, INNER_H + 1, max(CORNER_R - WALL, 0.5))
    base = outer - cavity

    # divider between battery and electronics, with a wire notch in the middle
    div = box(0, LIPO[1], 0, IN_L, DIVIDER_T, DIVIDER_H)
    div -= box(IN_L / 2 - 3, LIPO[1] - 1, DIVIDER_H - 3.5, 6, DIVIDER_T + 2, 4)
    base += div

    # XIAO rails (along x, under both long board edges) + end stop
    xy0 = ELEC_YC - XIAO[1] / 2
    for y in (xy0, xy0 + XIAO[1] - 1.5):
        base += box(XIAO_X0 + 2, y, 0, XIAO[0] - 2, 1.5, XIAO_RAIL_H)
    base += box(XIAO_X0 + XIAO[0] + 0.2, ELEC_YC - 3, 0, 1.2, 6, XIAO_RAIL_H + XIAO_PCB_T + 1.5)

    # USB-C cutout in -x wall (rounded slot around the plug overmold)
    usb_zc = XIAO_RAIL_H + XIAO_PCB_T + 1.6
    slot = Manifold.batch_hull([cyl_x(7.0, WALL + 2, -WALL - 1, ELEC_YC + dy, usb_zc) for dy in (-2.75, 2.75)])
    base -= slot

    # Mic platform: 4 corner posts so the flipped breakout sits just under the lid gasket
    plat_top = INNER_H - 1.5 - MIC_STACK_T
    my0 = ELEC_YC - MIC[1] / 2
    for px in (MIC_X0, MIC_X0 + MIC[0] - 2.5):
        for py in (my0, my0 + MIC[1] - 2.5):
            base += box(px, py, 0, 2.5, 2.5, plat_top)

    # FPC antenna recess on inside of +y wall (electronics side, away from the LiPo)
    fl, fh, fd = FPC_ANT
    base -= box((IN_L - fl) / 2, IN_W - 0.01, 0.5, fl, fd + 0.01, fh)

    # optional rod antenna / RP-SMA bulkhead hole in -x wall, battery side
    if ROD_ANT_HOLE_D > 0:
        base -= cyl_x(ROD_ANT_HOLE_D, WALL + 2, -WALL - 1, LIPO[1] / 2, INNER_H - LIP_H - ROD_ANT_HOLE_D / 2 - 0.8)

    # pry notch on +x top edge
    base -= box(IN_L - 0.5, IN_W / 2 - 4, INNER_H - 1.2, WALL + 1, 8, 2)
    return base.translate([WALL, WALL, FLOOR])


def make_lid():
    # Printed upside down: plate on the bed (z 0..LID), lip and gasket ring pointing up.
    # Lid x/y mirrors the base about y so features line up when flipped onto it.
    plate = rounded_box(-WALL, -WALL, 0, OUT_L, OUT_W, LID, CORNER_R)
    lo = CLEAR
    lip = box(lo, lo, LID, IN_L - 2 * lo, IN_W - 2 * lo, LIP_H) - \
        box(lo + LIP_T, lo + LIP_T, LID - 1, IN_L - 2 * (lo + LIP_T), IN_W - 2 * (lo + LIP_T), LIP_H + 2)
    lid = plate + lip

    # mic gasket ring + port hole (y mirrored: lid is flipped about the x axis)
    px = MIC_XC + MIC_PORT_OFFSET[0]
    py = IN_W - (ELEC_YC + MIC_PORT_OFFSET[1])
    ring = Manifold.cylinder(1.5, 3.0).translate([px, py, LID]) - Manifold.cylinder(2, 1.9).translate([px, py, LID])
    lid += ring
    lid -= Manifold.cylinder(LID + 4, MIC_PORT_D / 2).translate([px, py, -1])
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
        f.write(struct.pack("<80sI", b"Team-10 node case", len(t)))
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
