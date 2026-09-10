"""Find damaged regions on wall and ceiling surfaces.

No trained damage classifier here. Training one needs labelled damage and I
had no way to stage any, so instead this looks for what damage actually is
optically: a patch of a surface whose colour departs from the rest of that
surface. Water staining is discolouration, smoke is darkening, a hole is a
dark region with no return.

Working on one surface at a time is what makes this tractable. A wall is
mostly one colour, so "unlike the rest of this wall" is a meaningful signal in
a way that "unlike the rest of the room" is not.

This path has never been checked against damage of known extent. Treat every
number it produces as unvalidated - see the technical report, section 8.
"""

import json
import numpy as np
from pathlib import Path


def surface_colours(capture, poses, wall_normal, wall_offset, floor_y, ceiling_y,
                    t_min, t_max, cell=0.05, max_frames=40):
    """Paint a wall with the colours seen in the RGB frames.

    For each frame, project its pixels onto the wall plane and keep the ones
    that land on this wall segment. Returns a colour per wall cell plus how
    many samples backed it, so thinly seen cells can be ignored later.
    """
    from PIL import Image

    along = np.array([-wall_normal[1], wall_normal[0]])
    nt = int(np.ceil((t_max - t_min) / cell)) + 1
    nh = int(np.ceil((ceiling_y - floor_y) / cell)) + 1
    if nt < 4 or nh < 4:
        return None

    acc = np.zeros((nt, nh, 3), np.float64)
    cnt = np.zeros((nt, nh), np.int32)

    manifest = json.loads((Path(capture) / "manifest.json").read_text())
    dw, dh = manifest["depth_width"], manifest["depth_height"]

    step = max(1, len(poses) // max_frames)
    for p in poses[::step]:
        if p["tracking"] != "normal":
            continue
        dfile = Path(capture) / f"depth/{p['index']:06d}.bin"
        ffile = Path(capture) / f"frames/{p['index']:06d}.jpg"
        if not (dfile.exists() and ffile.exists()):
            continue

        depth = np.fromfile(dfile, dtype=np.float32).reshape(dh, dw)
        img = np.asarray(Image.open(ffile).convert("RGB").resize((dw, dh)))

        K, T = p["K"], p["T"]
        sx, sy = dw / p["w"], dh / p["h"]
        fx, fy = K[0, 0] * sx, K[1, 1] * sy
        cx, cy = K[0, 2] * sx, K[1, 2] * sy
        u, v = np.meshgrid(np.arange(dw), np.arange(dh))

        keep = (depth > 0.3) & (depth < 5.0)
        if not keep.any():
            continue
        z = depth[keep]
        x = (u[keep] + 0.5 - cx) / fx * z
        y = (v[keep] + 0.5 - cy) / fy * z
        pts = np.stack([x, -y, -z], 1) @ T[:3, :3].T + T[:3, 3]
        cols = img[keep]

        d = pts[:, [0, 2]] @ wall_normal - wall_offset
        on = np.abs(d) < 0.08
        if not on.any():
            continue
        pw, cw = pts[on], cols[on]
        t = pw[:, [0, 2]] @ along
        ti = ((t - t_min) / cell).astype(int)
        hi = ((pw[:, 1] - floor_y) / cell).astype(int)
        ok = (ti >= 0) & (hi >= 0) & (ti < nt) & (hi < nh)
        np.add.at(acc, (ti[ok], hi[ok]), cw[ok])
        np.add.at(cnt, (ti[ok], hi[ok]), 1)

    seen = cnt > 0
    if seen.sum() < 100:
        return None
    colour = np.zeros_like(acc)
    colour[seen] = acc[seen] / cnt[seen][:, None]
    return colour, cnt, cell, nt, nh


def find_damage(colour, cnt, cell, min_samples=5, z_thresh=4.0,
                min_area_m2=0.15, max_area_frac=0.30):
    """Cells whose colour is far from this surface's own median.

    The z-score is against the surface, not against any absolute idea of what
    drywall looks like, so a beige wall and a white ceiling are both handled
    without tuning. Regions covering more than a third of a surface are
    rejected: that is a lighting gradient or a shadow, not damage.
    """
    from scipy import ndimage

    seen = cnt >= min_samples
    if seen.sum() < 100:
        return []

    vals = colour[seen]
    med = np.median(vals, axis=0)
    mad = np.median(np.abs(vals - med), axis=0) + 1e-6

    dev = np.zeros(colour.shape[:2])
    dev[seen] = np.max(np.abs(colour[seen] - med) / (1.4826 * mad), axis=1)

    odd = (dev > z_thresh) & seen
    odd = ndimage.binary_opening(odd, structure=np.ones((3, 3), bool))
    odd = ndimage.binary_closing(odd, structure=np.ones((3, 3), bool))

    lbl, n = ndimage.label(odd)
    total_seen = seen.sum()
    out = []
    for i in range(1, n + 1):
        m = lbl == i
        area = m.sum() * cell * cell
        if area < min_area_m2:
            continue
        if m.sum() / total_seen > max_area_frac:
            continue

        ts, hs = np.nonzero(m)
        patch = colour[m]
        mean_col = patch.mean(0)
        darker = float(mean_col.mean() - med.mean())

        if darker < -35:
            cls = "burn_or_hole"
        elif darker < -12:
            cls = "water_staining"
        else:
            cls = "surface_discolouration"

        out.append({
            "damage_class": cls,
            "extent_m2": float(area),
            "bbox_on_surface": [float(ts.min() * cell), float(hs.min() * cell),
                                float((ts.max() + 1) * cell), float((hs.max() + 1) * cell)],
            "mean_deviation": float(dev[m].mean()),
            "brightness_delta": darker,
            "n_cells": int(m.sum()),
        })
    return out
