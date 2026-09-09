import numpy as np
from scipy import ndimage


def wall_slab(pts, wall_normal, wall_offset, thickness=0.10,
              t_min=None, t_max=None):
    """Points on this wall.

    The t_min/t_max bounds matter more than they look. A wall from the floor
    polygon is a short segment, but its plane is infinite and runs straight
    through the rest of the room, so without bounding it along the wall you
    collect points from surfaces metres away and every test downstream sees
    a room's worth of clutter.
    """
    d = pts[:, [0, 2]] @ wall_normal - wall_offset
    keep = np.abs(d) < thickness
    if t_min is not None:
        along = np.array([-wall_normal[1], wall_normal[0]])
        t = pts[:, [0, 2]] @ along
        keep &= (t >= t_min) & (t <= t_max)
    return pts[keep]


def occupancy_on_wall(slab, wall_normal, floor_y, ceiling_y, cell=0.05):
    """Flatten a wall's points onto the wall plane: distance along the wall
    against height."""
    along = np.array([-wall_normal[1], wall_normal[0]])
    t = slab[:, [0, 2]] @ along
    h = slab[:, 1]

    t0, h0 = t.min(), floor_y
    nt = int(np.ceil((t.max() - t0) / cell)) + 1
    nh = int(np.ceil((ceiling_y - h0) / cell)) + 1
    if nt < 4 or nh < 4:
        return None

    ti = np.clip(((t - t0) / cell).astype(int), 0, nt - 1)
    hi = np.clip(((h - h0) / cell).astype(int), 0, nh - 1)
    grid = np.zeros((nt, nh), dtype=bool)
    grid[ti, hi] = True

    grid = ndimage.binary_closing(grid, structure=np.ones((3, 3), bool))
    return grid, t0, h0, cell


def near_side_grid(pts, wall_normal, wall_offset, t0, h0, cell, shape,
                  t_min=None, t_max=None,
                   near=0.12, far=1.5, min_count=3):
    """Where is there something standing in front of this wall?

    This is the fix. An empty patch of wall means no laser came back from it,
    which happens for a real opening and also for a nightstand parked against
    it. If there are points hanging in the space just inside the room from
    that patch, something was in the way and it is not an opening.
    """
    d = pts[:, [0, 2]] @ wall_normal - wall_offset
    sel = (d < -near) & (d > -far)
    if t_min is not None:
        along_ = np.array([-wall_normal[1], wall_normal[0]])
        tt = pts[:, [0, 2]] @ along_
        sel &= (tt >= t_min) & (tt <= t_max)
    inside = pts[sel]
    if len(inside) == 0:
        return np.zeros(shape, bool)

    along = np.array([-wall_normal[1], wall_normal[0]])
    t = inside[:, [0, 2]] @ along
    h = inside[:, 1]
    ti = ((t - t0) / cell).astype(int)
    hi = ((h - h0) / cell).astype(int)
    ok = (ti >= 0) & (hi >= 0) & (ti < shape[0]) & (hi < shape[1])

    cnt = np.zeros(shape, int)
    np.add.at(cnt, (ti[ok], hi[ok]), 1)
    return ndimage.binary_dilation(cnt >= min_count, iterations=1)


def far_side_grid(pts, wall_normal, wall_offset, t0, h0, cell, shape,
                  t_min=None, t_max=None,
                  near=0.15, far=4.0, min_count=2):
    """Where is there space beyond this wall?

    A doorway has room on the other side. A patch of wall that is empty with
    nothing behind it is wall I never looked at, not an opening.
    """
    d = pts[:, [0, 2]] @ wall_normal - wall_offset
    sel = (d > near) & (d < far)
    if t_min is not None:
        along_ = np.array([-wall_normal[1], wall_normal[0]])
        tt = pts[:, [0, 2]] @ along_
        sel &= (tt >= t_min) & (tt <= t_max)
    beyond = pts[sel]
    if len(beyond) == 0:
        return np.zeros(shape, bool)

    along = np.array([-wall_normal[1], wall_normal[0]])
    t = beyond[:, [0, 2]] @ along
    h = beyond[:, 1]
    ti = ((t - t0) / cell).astype(int)
    hi = ((h - h0) / cell).astype(int)
    ok = (ti >= 0) & (hi >= 0) & (ti < shape[0]) & (hi < shape[1])

    cnt = np.zeros(shape, int)
    np.add.at(cnt, (ti[ok], hi[ok]), 1)
    return ndimage.binary_dilation(cnt >= min_count, iterations=2)


def find_openings(grid, occluded, beyond, t0, h0, cell, floor_y, ceiling_y,
                  min_width=0.45, max_width=2.60, min_height=0.55,
                  edge_margin_cells=3, min_fill=0.68, ceiling_margin=0.20,
                  max_occluded_frac=0.35, min_beyond_frac=0.25):
    """Empty regions that survive the occlusion and free-space tests.

    Rejections are returned as well as detections, so the fix loop can show
    what got thrown out and why.
    """
    empty = ~grid
    empty[:edge_margin_cells, :] = False
    empty[-edge_margin_cells:, :] = False
    empty[:, -edge_margin_cells:] = False

    lbl, n = ndimage.label(empty)
    out, rejected = [], []
    for i in range(1, n + 1):
        m = lbl == i
        ts, hs = np.nonzero(m)
        width = (ts.max() - ts.min() + 1) * cell
        height = (hs.max() - hs.min() + 1) * cell
        box = (ts.max() - ts.min() + 1) * (hs.max() - hs.min() + 1)
        fill = m.sum() / box
        sill = h0 + hs.min() * cell

        def note(reason):
            rejected.append({"reason": reason, "width_m": float(width),
                             "height_m": float(height),
                             "sill_height_m": float(sill - floor_y)})

        if not (min_width <= width <= max_width) or height < min_height:
            note("size")
            continue
        if fill < min_fill:
            note("ragged")
            continue
        if h0 + hs.max() * cell > ceiling_y - ceiling_margin and height < 1.0:
            note("hugs ceiling, unobserved wall")
            continue

        occ_frac = float(occluded[m].mean())
        if occ_frac > max_occluded_frac:
            note("occluded by something nearer (%.0f%% of cells)" % (100 * occ_frac))
            continue

        beyond_frac = float(beyond[m].mean())
        if beyond_frac < min_beyond_frac:
            note("no space beyond it (%.0f%% of cells)" % (100 * beyond_frac))
            continue

        reaches_floor = (sill - floor_y) < 0.15
        if reaches_floor:
            kind = "door" if height > 1.4 else "pass_through"
        else:
            kind = "window"

        out.append({
            "kind": kind,
            "width_m": float(width),
            "height_m": float(height),
            "sill_height_m": float(sill - floor_y),
            "top_height_m": float(h0 + hs.max() * cell - floor_y),
            "centre_along_wall_m": float(t0 + (ts.min() + ts.max()) / 2 * cell),
            "n_empty_cells": int(m.sum()),
            "fill_ratio": float(fill),
            "occluded_fraction": occ_frac,
            "beyond_fraction": beyond_frac,
        })
    return out, rejected


def openings_for_wall(pts, wall_normal, wall_offset, floor_y, ceiling_y,
                      cell=0.05, return_rejected=False,
                      start=None, end=None, pad=0.10):
    """start and end are the wall segment's endpoints in the same frame as
    the point cloud. Pass them: without the segment bounds this measures a
    plane that slices the whole room, not a wall."""
    wall_normal = np.asarray(wall_normal, dtype=float)
    t_min = t_max = None
    if start is not None and end is not None:
        along = np.array([-wall_normal[1], wall_normal[0]])
        ta, tb = np.asarray(start) @ along, np.asarray(end) @ along
        t_min, t_max = min(ta, tb) - pad, max(ta, tb) + pad
    slab = wall_slab(pts, wall_normal, wall_offset, t_min=t_min, t_max=t_max)
    if len(slab) < 500:
        return ([], []) if return_rejected else []

    packed = occupancy_on_wall(slab, wall_normal, floor_y, ceiling_y, cell=cell)
    if packed is None:
        return ([], []) if return_rejected else []
    grid, t0, h0, cell = packed

    occluded = near_side_grid(pts, wall_normal, wall_offset, t0, h0, cell,
                              grid.shape, t_min=t_min, t_max=t_max)
    beyond = far_side_grid(pts, wall_normal, wall_offset, t0, h0, cell,
                           grid.shape, t_min=t_min, t_max=t_max)

    found, rejected = find_openings(grid, occluded, beyond, t0, h0, cell,
                                    floor_y, ceiling_y)
    return (found, rejected) if return_rejected else found
