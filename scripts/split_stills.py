"""Split a single stills folder into one folder per room.

The photo tier's contract is "a set of photo folders, one folder per room".
In normal use you type the room name in the capture app before shooting that
room, and the app writes the folders directly. On capture_1788930419 I left
one room name in the field for the whole session, so all 49 stills landed in
one folder and the photo tier saw a single room.

Rather than sorting them by hand, this recovers the split from the data:

  1. Match each still to the walkthrough frame it was taken beside, by
     normalised correlation on a 32x24 greyscale thumbnail. Median match
     confidence on this capture is 0.99, and the matched frame indices come
     out monotonically increasing, which is what you would expect if the
     stills were taken in walking order.
  2. Read that frame's camera position from poses.jsonl.
  3. Look up which room that position falls in, using the same segmentation
     the LiDAR tier produces.
  4. Keep at most 8 stills per room, evenly spaced, since the spec asks for
     2 to 8 per room.

The LiDAR tier is used here only to *label* folders, which is a data
preparation step a user would otherwise do by typing a room name. No pose or
depth reaches the photo tier itself - it still sees nothing but JPEGs.

    python3 scripts/split_stills.py --capture benchmark/captures/capture_1788930419
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from scipy.ndimage import uniform_filter1d

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ingest.lidar import load_poses, unproject, voxel_downsample
from pipeline.geometry.drift import loop_closure_correction
from pipeline.geometry.outline import wall_heading, rotation, footprint
from pipeline.geometry.rooms import wall_grid, segment_rooms

MAX_PER_ROOM = 8


def thumb(path, size=(32, 24)):
    a = np.asarray(Image.open(path).convert("L").resize(size), dtype=np.float32).ravel()
    return (a - a.mean()) / (a.std() + 1e-6)


def match_stills_to_frames(capture, stills):
    frames = sorted((capture / "frames").glob("*.jpg"))
    F = np.stack([thumb(f) for f in frames])
    idx = [int(f.stem) for f in frames]
    out = []
    for s in stills:
        q = thumb(s)
        c = F @ q / len(q)
        j = int(c.argmax())
        out.append((idx[j], float(c[j])))
    return out


def room_map(capture):
    """Same geometry the LiDAR tier runs, used only to label positions."""
    m = json.loads((capture / "manifest.json").read_text())
    dw, dh = m["depth_width"], m["depth_height"]
    poses, _ = loop_closure_correction(load_poses(capture))

    A = []
    for p in poses[::4]:
        f = capture / f"depth/{p['index']:06d}.bin"
        if not f.exists():
            continue
        d = np.fromfile(f, dtype=np.float32).reshape(dh, dw)
        q, _ = unproject(d, p["K"], p["T"], p["w"], p["h"])
        A.append(q)
    pts = np.concatenate(A)
    pts, _ = voxel_downsample(pts, np.zeros(len(pts), np.uint8), 0.03)

    tree = cKDTree(pts)
    idx = np.random.default_rng(0).choice(len(pts), size=min(200000, len(pts)), replace=False)
    _, nb = tree.query(pts[idx], k=60)
    nm = np.empty((len(idx), 3))
    for i, r in enumerate(nb):
        c = pts[r] - pts[r].mean(0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        nm[i] = vt[2]

    P = pts[idx]
    hp = P[np.abs(nm[:, 1]) > 0.95]
    h = hp[:, 1]
    cam_y = float(np.median([p["T"][1, 3] for p in poses]))
    bins = np.arange(h.min(), h.max() + 0.01, 0.01)
    hist, e = np.histogram(h, bins=bins)
    c = (e[:-1] + e[1:]) / 2
    sm = uniform_filter1d(hist.astype(float), 5)
    loc = [i for i in range(2, len(sm) - 2)
           if sm[i] == max(sm[i - 2:i + 3]) and sm[i] > 0.05 * sm.max()]

    def area(y):
        b = hp[np.abs(hp[:, 1] - y) < 0.06]
        if len(b) < 50:
            return 0.0
        return len(set(map(tuple, np.floor(b[:, [0, 2]] / 0.15).astype(int)))) * 0.0225

    below = [(c[i], area(c[i])) for i in loc if c[i] < cam_y - 0.4 and area(c[i]) > 0.5]
    above = [(c[i], area(c[i])) for i in loc if c[i] > cam_y + 0.2 and area(c[i]) > 0.5]
    if not below or not above:
        raise SystemExit("could not find floor and ceiling")
    fl = max(below, key=lambda t: t[1])[0]
    high = [x for x in above if x[0] - fl >= 2.0] or above
    ce = max(high, key=lambda t: t[1])[0]

    theta = wall_heading(nm)
    R = rotation(theta)
    floor = P[(np.abs(nm[:, 1]) > 0.95) & (np.abs(P[:, 1] - fl) < 0.08)]
    grid, origin, cell = footprint(floor[:, [0, 2]] @ R.T, cell=0.08)
    wallpts = P[(np.abs(nm[:, 1]) < 0.25) & (P[:, 1] > fl + 0.3) & (P[:, 1] < ce - 0.3)]
    wg = wall_grid(wallpts[:, [0, 2]] @ R.T, grid.shape, origin, cell)
    rooms, n = segment_rooms(grid, wg, cell)

    positions = {p["index"]: p["T"][:3, 3] for p in poses}
    return rooms, origin, cell, R, positions, n


def locate(xz_world, rooms, origin, cell, R):
    g = np.floor((xz_world @ R.T) / cell).astype(int) - origin
    g = np.clip(g, [0, 0], [rooms.shape[0] - 1, rooms.shape[1] - 1])
    r = int(rooms[g[0], g[1]])
    if r == 0:                       # doorway or just outside; take the nearest room
        occupied = np.array(np.nonzero(rooms > 0)).T
        j = int(((occupied - g) ** 2).sum(1).argmin())
        r = int(rooms[occupied[j][0], occupied[j][1]])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    capture = Path(a.capture)

    folders = [d for d in (capture / "stills").iterdir() if d.is_dir()]
    if len(folders) > 1:
        print("already split into %d folders, nothing to do" % len(folders))
        return
    src = folders[0]
    stills = sorted(src.glob("*.jpg"))
    print("%d stills in one folder (%s)" % (len(stills), src.name))

    matched = match_stills_to_frames(capture, stills)
    conf = [c for _, c in matched]
    print("frame match confidence: min %.2f median %.2f" % (min(conf), float(np.median(conf))))

    rooms, origin, cell, R, positions, n_rooms = room_map(capture)
    print("segmentation found %d rooms" % n_rooms)

    by_room = {}
    for s, (fi, _) in zip(stills, matched):
        if fi not in positions:
            continue
        r = locate(positions[fi][[0, 2]], rooms, origin, cell, R)
        by_room.setdefault(r, []).append(s)

    for r, group in sorted(by_room.items()):
        if len(group) > MAX_PER_ROOM:
            keep = np.linspace(0, len(group) - 1, MAX_PER_ROOM).astype(int)
            group = [group[i] for i in keep]
        name = f"room_{r}"
        print("  %s: %d stills" % (name, len(group)))
        if a.dry_run:
            continue
        dest = capture / "stills" / name
        dest.mkdir(parents=True, exist_ok=True)
        for k, s in enumerate(group):
            shutil.copy2(s, dest / f"still_{k:03d}.jpg")

    if not a.dry_run:
        shutil.rmtree(src)
        print("removed the original single folder")


if __name__ == "__main__":
    main()
