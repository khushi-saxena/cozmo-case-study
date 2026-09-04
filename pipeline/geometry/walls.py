import numpy as np
from scipy.spatial import cKDTree


def surface_normals(pts, k=60, sample=200_000, seed=0):
    tree = cKDTree(pts)
    if sample is None or sample >= len(pts):
        idx = np.arange(len(pts))
    else:
        idx = np.random.default_rng(seed).choice(len(pts), size=sample, replace=False)
    _, nbrs = tree.query(pts[idx], k=k)
    out = np.empty((len(idx), 3))
    for i, ring in enumerate(nbrs):
        c = pts[ring] - pts[ring].mean(0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        out[i] = vt[2]
    return idx, out


def wall_points(pts, floor_y, ceiling_y, margin=0.25, tol=0.25):
    """Points on vertical surfaces, staying clear of skirting and cornice where
    the wall curves into the floor and ceiling."""
    band = pts[(pts[:, 1] > floor_y + margin) & (pts[:, 1] < ceiling_y - margin)]
    idx, n = surface_normals(band)
    keep = np.abs(n[:, 1]) < tol
    return band[idx][keep], n[keep]


def dominant_angles(normals, bins=180):
    """Wall normals projected to the floor plane. A rectangular room gives two
    directions 90 degrees apart, at whatever heading ARKit happened to start on."""
    a = np.degrees(np.arctan2(normals[:, 2], normals[:, 0])) % 180
    hist, edges = np.histogram(a, bins=bins, range=(0, 180))
    peak = (edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2
    return peak, hist, edges


def fit_line_2d(P, iters=10, thresh=0.03):
    """Total least squares line through 2D points, reweighted to drop outliers.
    Returns unit normal and offset so that n . p = d."""
    w = np.ones(len(P))
    n = d = None
    for _ in range(iters):
        m = np.average(P, axis=0, weights=w)
        c = (P - m) * w[:, None]
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        n = vt[1]
        d = n @ m
        r = P @ n - d
        w = (np.abs(r) < thresh).astype(float)
        if w.sum() < 20:
            break
    inl = np.abs(P @ n - d) < thresh
    return n, d, inl


def extract_walls(pts3, min_inliers=800, thresh=0.03, max_walls=16,
                  min_length=0.6, clear=0.08, min_coverage=0.7):
    """Pull walls out one at a time, strongest first.

    Two things this has to get right. Removing only the points within `thresh`
    leaves the plane's own noise behind and the same wall gets found again next
    round, so removal uses a wider band. And a wardrobe face looks exactly like
    a wall in 2D, so a candidate only counts if its points span most of the
    floor-to-ceiling band."""
    xz = pts3[:, [0, 2]]
    y = pts3[:, 1]
    y_lo, y_hi = y.min(), y.max()
    n_ybins = 10
    remaining = np.ones(len(xz), dtype=bool)
    walls = []
    rng = np.random.default_rng(0)

    for _ in range(max_walls):
        P = xz[remaining]
        if len(P) < min_inliers:
            break

        best = None
        for _ in range(400):
            i, j = rng.choice(len(P), size=2, replace=False)
            v = P[j] - P[i]
            L = np.linalg.norm(v)
            if L < 0.5:
                continue
            n = np.array([-v[1], v[0]]) / L
            d = n @ P[i]
            cnt = int((np.abs(P @ n - d) < thresh).sum())
            if best is None or cnt > best[0]:
                best = (cnt, n, d)

        if best is None or best[0] < min_inliers:
            break

        n, d, inl = fit_line_2d(P[np.abs(P @ best[1] - best[2]) < thresh])
        on = np.abs(P @ n - d) < thresh
        if on.sum() < min_inliers:
            break

        Y = y[remaining][on]
        filled = np.unique(np.clip(
            ((Y - y_lo) / (y_hi - y_lo) * n_ybins).astype(int), 0, n_ybins - 1))
        coverage = len(filled) / n_ybins

        # extent along the wall, and check the points are not just a short clump
        t = P[on] @ np.array([-n[1], n[0]])
        lo, hi = np.percentile(t, [1, 99])
        if hi - lo < min_length:
            remaining[np.flatnonzero(remaining)[
                np.abs(P @ n - d) < thresh + clear]] = False
            continue

        wide = np.abs(P @ n - d) < thresh + clear
        if coverage < min_coverage:
            # furniture face, not a wall: drop the points and move on
            remaining[np.flatnonzero(remaining)[wide]] = False
            continue

        walls.append({
            "normal": n,
            "offset": float(d),
            "coverage": float(coverage),
            "t_min": float(lo),
            "t_max": float(hi),
            "length_raw": float(hi - lo),
            "inliers": int(on.sum()),
            "angle_deg": float(np.degrees(np.arctan2(n[1], n[0])) % 180),
        })
        remaining[np.flatnonzero(remaining)[wide]] = False

    return walls


def order_and_close(walls, centre):
    """Take the walls that bound the room, order them around the centre and
    intersect neighbours to get corners."""
    if len(walls) < 3:
        return None, walls

    # a bounding wall faces the centre; flip normals so they all point inward
    for w in walls:
        if w["normal"] @ (centre - w["normal"] * w["offset"]) < 0:
            w["normal"] = -w["normal"]
            w["offset"] = -w["offset"]

    walls = sorted(walls, key=lambda w: np.arctan2(w["normal"][1], w["normal"][0]))

    corners = []
    for i in range(len(walls)):
        a, b = walls[i], walls[(i + 1) % len(walls)]
        A = np.array([a["normal"], b["normal"]])
        if abs(np.linalg.det(A)) < 0.15:      # near parallel, no usable corner
            continue
        corners.append(np.linalg.solve(A, [a["offset"], b["offset"]]))

    return (np.array(corners) if len(corners) >= 3 else None), walls


def polygon_area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def polygon_edges(poly):
    return [float(np.linalg.norm(poly[(i + 1) % len(poly)] - poly[i]))
            for i in range(len(poly))]
