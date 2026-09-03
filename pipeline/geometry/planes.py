import numpy as np
from scipy.spatial import cKDTree


def estimate_normals(pts, k=24, sample=250_000, seed=0):
    """Local PCA on each neighbourhood. Smallest eigenvector is the normal."""
    tree = cKDTree(pts)
    if sample is None or sample >= len(pts):
        idx = np.arange(len(pts))
    else:
        idx = np.random.default_rng(seed).choice(len(pts), size=sample, replace=False)

    _, nbrs = tree.query(pts[idx], k=k)
    normals = np.empty((len(idx), 3))
    for i, ring in enumerate(nbrs):
        c = pts[ring] - pts[ring].mean(0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        normals[i] = vt[2]
    return idx, normals


def horizontal_heights(pts, idx, normals, cos_tol=0.94):
    """Y values of points that sit on something horizontal. Walls contribute
    points at every height, so filtering by normal is what makes floor and
    ceiling stand out at all."""
    horiz = np.abs(normals[:, 1]) > cos_tol
    return pts[idx][horiz][:, 1]


def find_peaks(heights, bin_size=0.01, min_gap=0.3, n=8):
    bins = np.arange(heights.min(), heights.max() + bin_size, bin_size)
    hist, edges = np.histogram(heights, bins=bins)
    centres = (edges[:-1] + edges[1:]) / 2

    peaks = []
    for i in np.argsort(hist)[::-1]:
        if all(abs(centres[i] - y) > min_gap for y, _ in peaks):
            peaks.append((centres[i], int(hist[i])))
        if len(peaks) >= n:
            break
    return sorted(peaks), centres, hist


def refine(heights, y0, window=0.05):
    band = heights[np.abs(heights - y0) < window]
    if len(band) < 30:
        return None
    lo, hi = np.percentile(band, [10, 90])
    core = band[(band >= lo) & (band <= hi)]
    return {"height": float(core.mean()), "std": float(core.std()), "n": int(len(band))}


def ceiling_height(pts, camera_y, sample=250_000, support_frac=0.25):
    """Floor and ceiling are the best-supported horizontal planes below and
    above the camera. Taking the lowest and highest instead picks up light
    fittings and doorframe tops, which moves the answer by 20cm+ depending on
    how many frames you happen to feed in."""
    idx, normals = estimate_normals(pts, sample=sample)
    heights = horizontal_heights(pts, idx, normals)
    peaks, _, _ = find_peaks(heights)

    # a peak only counts if it has real support, otherwise light fittings and
    # doorframe tops get mistaken for the ceiling
    floor_ = max(c for _, c in peaks)
    solid = [(y, c) for y, c in peaks if c >= support_frac * floor_]

    below = [y for y, _ in solid if y < camera_y - 0.4]
    above = [y for y, _ in solid if y > camera_y + 0.2]
    if not below or not above:
        return None

    # lowest and highest of the well-supported planes: taking the strongest
    # instead picks up beds and tabletops, which are better observed than the
    # floor when you walk at chest height
    floor = refine(heights, min(below))
    ceiling = refine(heights, max(above))
    if floor is None or ceiling is None:
        return None

    return {
        "floor_y": floor["height"],
        "ceiling_y": ceiling["height"],
        "height_m": ceiling["height"] - floor["height"],
        "floor_std": floor["std"],
        "ceiling_std": ceiling["std"],
        "floor_n": floor["n"],
        "ceiling_n": ceiling["n"],
        "intermediate_surfaces": [round(y, 3) for y, _ in peaks
                                  if floor["height"] + 0.15 < y < ceiling["height"] - 0.15],
    }
