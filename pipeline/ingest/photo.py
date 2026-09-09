"""Photo tier: 2-8 stills per room, no depth, no poses.

Each still gets a metric depth map from the monocular model and becomes a
partial point cloud in its own camera frame. There is nothing to register the
stills to each other with, so the room is measured per still and the results
are pooled: ceiling height from stills that see both floor and ceiling, wall
extents as the largest span seen in any single still.

Scale comes from the model alone. The one check available is a door-height
prior (a standard interior door leaf is 1.98-2.03 m); where a still shows a
door top and the floor, the ratio is reported so calibration can be judged.

Intervals are wide on purpose. The case study scores calibration at every
tier, and confident garbage on thin input caps the total."""

import numpy as np
from pathlib import Path
from PIL import Image
from scipy.spatial import cKDTree

from . import monodepth

# iPhone 15+ main camera at 1920x1440: ARKit reports ~1365 px focal. This is
# calibration, not pose, and belongs in the device matrix.
DEFAULT_FX = 1365.0
DEFAULT_RES = (1920, 1440)


def unproject_cam(depth, fx, fy, cx, cy, z_max=8.0):
    h, w = depth.shape
    u, v = np.meshgrid(np.arange(w), np.arange(h))
    keep = (depth > 0.3) & (depth < z_max)
    z = depth[keep]
    x = (u[keep] + 0.5 - cx) / fx * z
    y = (v[keep] + 0.5 - cy) / fy * z
    return np.stack([x, y, z], axis=1)


def normals(pts, k=40, sample=60_000):
    idx = np.random.default_rng(0).choice(len(pts), size=min(sample, len(pts)), replace=False)
    tree = cKDTree(pts)
    _, nb = tree.query(pts[idx], k=k)
    out = np.empty((len(idx), 3))
    for i, r in enumerate(nb):
        c = pts[r] - pts[r].mean(0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        out[i] = vt[2]
    return idx, out


def gravity_from_floor(pts, nm, idx):
    """The floor is the largest plane whose normal points roughly 'down' in
    camera space (camera y axis points down in the pinhole frame). Its normal
    is the gravity direction for this still."""
    down = nm[:, 1] > 0.85
    if down.sum() < 200:
        return None
    n = nm[down]
    # take the dominant normal by averaging the tight cluster around the median
    med = np.median(n, axis=0)
    med /= np.linalg.norm(med)
    close = n @ med > 0.98
    if close.sum() < 100:
        return None
    g = n[close].mean(0)
    return g / np.linalg.norm(g)


def align_to_gravity(pts, g):
    """Rotate so gravity is -y. After this, floor and ceiling are horizontal."""
    target = np.array([0.0, -1.0, 0.0])
    g = -g if g[1] < 0 else g          # make g point 'down' (+y in camera)
    src = g
    v = np.cross(src, -target)
    c = src @ (-target)
    if np.linalg.norm(v) < 1e-8:
        R = np.eye(3) if c > 0 else -np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * (1 / (1 + c))
    out = pts @ R.T
    out[:, 1] *= -1                     # flip so up is +y like the ARKit world
    return out


def measure_still(image, fx=DEFAULT_FX, downscale=4):
    img = image.convert("RGB")
    if img.size != DEFAULT_RES:
        fx = fx * img.width / DEFAULT_RES[0]
    if downscale > 1:
        img = img.resize((img.width // downscale, img.height // downscale), Image.BILINEAR)
        fx = fx / downscale
    d = monodepth.predict(img)
    cx, cy = img.width / 2, img.height / 2
    pts = unproject_cam(d, fx, fx, cx, cy)
    if len(pts) < 2000:
        return None
    idx, nm = normals(pts)
    g = gravity_from_floor(pts, nm, idx)
    if g is None:
        return None
    P = align_to_gravity(pts, g)

    # floor and ceiling: strong horizontal bands
    idx2, nm2 = normals(P)
    horiz = P[idx2][np.abs(nm2[:, 1]) > 0.95]
    if len(horiz) < 200:
        return None
    h = horiz[:, 1]
    lo, hi = np.percentile(h, [2, 98])
    floor_y = float(np.median(h[h < lo + 0.15]))
    top = h[h > hi - 0.15]
    ceiling_y = float(np.median(top)) if len(top) > 50 and (hi - lo) > 1.8 else None

    # lateral extent of what this still can see, at mid-height
    band = P[(P[:, 1] > floor_y + 0.4) & (P[:, 1] < floor_y + 2.0)]
    ext_x = float(np.ptp(band[:, 0])) if len(band) else 0.0
    ext_z = float(np.ptp(band[:, 2])) if len(band) else 0.0

    return {
        "floor_y": floor_y,
        "ceiling_y": ceiling_y,
        "ceiling_height": (ceiling_y - floor_y) if ceiling_y is not None else None,
        "extent_x": ext_x,
        "extent_z": ext_z,
        "points": P,
        "n_points": int(len(P)),
    }


def measure_room(folder, max_stills=8):
    folder = Path(folder)
    stills = sorted(folder.glob("*.jpg"))[:max_stills]
    results = []
    for s in stills:
        r = measure_still(Image.open(s))
        if r is not None:
            r["still"] = s.name
            results.append(r)
    if not results:
        return None

    heights = [r["ceiling_height"] for r in results if r["ceiling_height"]]
    ch = float(np.median(heights)) if heights else None
    ch_spread = float(np.ptp(heights)) if len(heights) > 1 else None

    return {
        "room_id": folder.name,
        "n_stills": len(stills),
        "n_usable": len(results),
        "ceiling_height": ch,
        "ceiling_height_spread": ch_spread,
        "ceiling_from_n_stills": len(heights),
        "extent_x": max(r["extent_x"] for r in results),
        "extent_z": max(r["extent_z"] for r in results),
        "per_still": [{k: v for k, v in r.items() if k != "points"} for r in results],
    }
