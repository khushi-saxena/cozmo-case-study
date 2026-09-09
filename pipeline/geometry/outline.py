import numpy as np
from scipy import ndimage


def wall_heading(normals, tol=0.25):
    """Rooms are rarely aligned with ARKit's axes, since X and Z come from
    whichever way the phone was pointing when the session started. Find the
    dominant wall direction so everything downstream can work axis-aligned."""
    vn = normals[np.abs(normals[:, 1]) < tol]
    a = np.degrees(np.arctan2(vn[:, 2], vn[:, 0])) % 90
    hist, edges = np.histogram(a, bins=90, range=(0, 90))
    return np.radians((edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2)


def rotation(theta):
    c, s = np.cos(-theta), np.sin(-theta)
    return np.array([[c, -s], [s, c]])


def footprint(floor_xz, cell=0.08, close_radius=3, min_area_cells=200):
    """Rasterise the floor points, close the gaps furniture leaves, and keep the
    largest blob. Furniture sits inside the room so it only ever punches holes,
    never extends the outline."""
    g = np.floor(floor_xz / cell).astype(int)
    origin = g.min(0)
    g -= origin
    grid = np.zeros(g.max(0) + 1, dtype=bool)
    grid[g[:, 0], g[:, 1]] = True

    # bridge the gaps where a sofa or bed hid the floor
    k = np.ones((close_radius * 2 + 1,) * 2, dtype=bool)
    grid = ndimage.binary_closing(grid, structure=k)

    lbl, n = ndimage.label(grid)
    if n == 0:
        return None, origin, cell
    sizes = ndimage.sum(grid, lbl, range(1, n + 1))
    if sizes.max() < min_area_cells:
        return None, origin, cell
    grid = lbl == (sizes.argmax() + 1)

    # furniture holes are interior, so filling them recovers the real floor
    grid = ndimage.binary_fill_holes(grid)
    return grid, origin, cell


def trace_outline(grid):
    """Moore-neighbour boundary walk. Sorting boundary pixels by angle about the
    centroid seems like it should work and does not: it zigzags and turns a
    4-corner room into 75 corners."""
    ys, xs = np.nonzero(grid)
    if len(ys) < 8:
        return None
    start = (ys.min(), xs[ys == ys.min()].min())

    # clockwise from north
    nbr = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
    H, W = grid.shape

    def solid(p):
        return 0 <= p[0] < H and 0 <= p[1] < W and grid[p]

    contour = [start]
    cur = start
    back = 6                      # came from the west
    for _ in range(8 * grid.sum()):
        found = False
        for step in range(8):
            k = (back + 1 + step) % 8
            nxt = (cur[0] + nbr[k][0], cur[1] + nbr[k][1])
            if solid(nxt):
                back = (k + 4) % 8
                cur = nxt
                found = True
                break
        if not found:
            break
        if cur == start and len(contour) > 2:
            break
        contour.append(cur)

    return np.array(contour, dtype=float)


def simplify(poly, tol=0.10, cell=0.08):
    """Douglas-Peucker in metres."""
    P = poly * cell

    def rdp(pts, eps):
        if len(pts) < 3:
            return pts
        a, b = pts[0], pts[-1]
        v = b - a
        L = np.linalg.norm(v)
        if L < 1e-9:
            d = np.linalg.norm(pts - a, axis=1)
        else:
            n = np.array([-v[1], v[0]]) / L
            d = np.abs((pts - a) @ n)
        i = int(d.argmax())
        if d[i] <= eps:
            return np.array([a, b])
        return np.vstack([rdp(pts[:i + 1], eps)[:-1], rdp(pts[i:], eps)])

    closed = np.vstack([P, P[:1]])
    out = rdp(closed, tol)
    return out[:-1] / cell


def snap_to_axes(poly, cell=0.08, tol=0.25):
    """After rectifying, real walls run along the axes. Snap near-axis edges so
    wall lengths are not eaten by rasterisation noise."""
    P = (poly * cell).copy()
    n = len(P)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        d = b - a
        if abs(d[0]) < tol and abs(d[1]) > abs(d[0]):
            m = (a[0] + b[0]) / 2
            P[i][0] = P[(i + 1) % n][0] = m
        elif abs(d[1]) < tol and abs(d[0]) > abs(d[1]):
            m = (a[1] + b[1]) / 2
            P[i][1] = P[(i + 1) % n][1] = m
    return P


def drop_short_edges(P, min_len=0.20):
    keep = [P[0]]
    for p in P[1:]:
        if np.linalg.norm(p - keep[-1]) >= min_len:
            keep.append(p)
    out = np.array(keep)
    if len(out) > 3 and np.linalg.norm(out[0] - out[-1]) < min_len:
        out = out[:-1]
    return out


def merge_collinear(P, angle_tol=12.0):
    """Rasterising a wall leaves a staircase, and Douglas-Peucker keeps each
    step as a corner. Fold consecutive edges that run the same way."""
    if len(P) < 4:
        return P
    keep = list(P)
    changed = True
    while changed and len(keep) > 4:
        changed = False
        n = len(keep)
        for i in range(n):
            a, b, c = keep[i], keep[(i + 1) % n], keep[(i + 2) % n]
            d1, d2 = b - a, c - b
            l1, l2 = np.linalg.norm(d1), np.linalg.norm(d2)
            if l1 < 1e-9 or l2 < 1e-9:
                continue
            ang = np.degrees(np.arccos(np.clip(d1 @ d2 / (l1 * l2), -1, 1)))
            if ang < angle_tol:
                del keep[(i + 1) % n]
                changed = True
                break
    return np.array(keep)


def area(P):
    x, y = P[:, 0], P[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def edges(P):
    return [float(np.linalg.norm(P[(i + 1) % len(P)] - P[i])) for i in range(len(P))]


def room_outline(pts, normals, idx, floor_y, cell=0.08):
    theta = wall_heading(normals)
    R = rotation(theta)

    P = pts[idx]
    floor = P[(np.abs(normals[:, 1]) > 0.98) & (np.abs(P[:, 1] - floor_y) < 0.08)]
    if len(floor) < 200:
        return None
    fr = floor[:, [0, 2]] @ R.T

    grid, origin, cell = footprint(fr, cell=cell)
    if grid is None:
        return None
    outline = trace_outline(grid)
    if outline is None:
        return None

    poly = simplify(outline, tol=0.20, cell=cell)
    poly = snap_to_axes(poly, cell=cell)
    poly = drop_short_edges(poly, min_len=0.30)
    poly = merge_collinear(poly)

    return {
        "heading_deg": float(np.degrees(theta)),
        "polygon_local": poly + origin * cell,
        "area_m2": area(poly),
        "wall_lengths_m": edges(poly),
        "n_corners": len(poly),
        "raster_area_m2": float(grid.sum() * cell * cell),
    }
