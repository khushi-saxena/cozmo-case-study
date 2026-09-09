import numpy as np
from scipy import ndimage


def wall_slab(pts, wall_normal, wall_offset, thickness=0.10):
    """Points belonging to one wall plane."""
    d = pts[:, [0, 2]] @ wall_normal - wall_offset
    return pts[np.abs(d) < thickness]


def occupancy_on_wall(slab, wall_normal, floor_y, ceiling_y, cell=0.05):
    """Flatten a wall's points onto the wall plane: along-wall distance against
    height. A door is a column of empty cells reaching the floor, a window is a
    patch of empty cells that does not."""
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

    # a single missing cell is sensor noise, not an opening
    grid = ndimage.binary_closing(grid, structure=np.ones((3, 3), bool))
    return grid, t0, h0, cell


def find_openings(grid, t0, h0, cell, floor_y, ceiling_y,
                  min_width=0.45, max_width=2.60, min_height=0.55,
                  edge_margin_cells=3, min_fill=0.68, ceiling_margin=0.20):
    """Empty regions in the wall's occupancy, filtered to plausible openings.

    Both a missed opening and a phantom opening count as a miss, so this is
    deliberately conservative: regions touching the ends of the wall are
    dropped, since a wall that simply ran out of observed points looks exactly
    like a doorway at the edge.

    Note this only sees openings that are actually open. A closed door leaf sits
    a few centimetres behind its frame, inside the wall slab, and reads as solid
    wall. The capture protocol has to require interior doors be opened first."""
    empty = ~grid
    nt, nh = grid.shape

    # ignore the outermost columns: those are usually just unobserved wall
    empty[:edge_margin_cells, :] = False
    empty[-edge_margin_cells:, :] = False
    empty[:, -edge_margin_cells:] = False

    lbl, n = ndimage.label(empty)
    out = []
    for i in range(1, n + 1):
        m = lbl == i
        ts, hs = np.nonzero(m)
        width = (ts.max() - ts.min() + 1) * cell
        height = (hs.max() - hs.min() + 1) * cell
        if not (min_width <= width <= max_width) or height < min_height:
            continue

        # fill ratio guards against ragged noise being read as an opening
        if m.sum() / ((ts.max() - ts.min() + 1) * (hs.max() - hs.min() + 1)) < min_fill:
            continue

        # a gap hugging the ceiling is almost always wall we never observed,
        # and a phantom opening is scored the same as a missed one
        if h0 + hs.max() * cell > ceiling_y - ceiling_margin and height < 1.0:
            continue

        sill = h0 + hs.min() * cell
        reaches_floor = (sill - floor_y) < 0.15
        top = h0 + hs.max() * cell
        kind = "door" if reaches_floor and height > 1.4 else (
            "window" if not reaches_floor else "pass_through")

        out.append({
            "kind": kind,
            "width_m": float(width),
            "height_m": float(height),
            "sill_height_m": float(sill - floor_y),
            "top_height_m": float(top - floor_y),
            "centre_along_wall_m": float(t0 + (ts.min() + ts.max()) / 2 * cell),
            "n_empty_cells": int(m.sum()),
            "fill_ratio": float(m.sum() / ((ts.max() - ts.min() + 1) *
                                           (hs.max() - hs.min() + 1))),
        })
    return out


def openings_for_wall(pts, wall_normal, wall_offset, floor_y, ceiling_y,
                      cell=0.05):
    slab = wall_slab(pts, np.asarray(wall_normal), wall_offset)
    if len(slab) < 500:
        return []
    packed = occupancy_on_wall(slab, np.asarray(wall_normal),
                               floor_y, ceiling_y, cell=cell)
    if packed is None:
        return []
    grid, t0, h0, cell = packed
    return find_openings(grid, t0, h0, cell, floor_y, ceiling_y)
