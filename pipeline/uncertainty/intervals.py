import numpy as np

# Per-tier priors on how well a single measurement can be trusted, before any
# evidence from the capture itself. These get calibrated against tape ground
# truth, they are not guesses left as-is.
TIER_PRIOR_M = {
    "lidar": 0.010,
    "video": 0.030,
    "photo": 0.080,
}

# Relative component, which is what dominates on long walls and on thin input
TIER_PRIOR_REL = {
    "lidar": 0.004,
    "video": 0.030,
    "photo": 0.080,
}

Z90 = 1.645


def measurement(value, unit, sigma, method, n_points=None, level=0.90):
    z = Z90 if abs(level - 0.90) < 1e-6 else 1.96
    m = {
        "value": float(value),
        "unit": unit,
        "ci_low": float(value - z * sigma),
        "ci_high": float(value + z * sigma),
        "ci_level": level,
        "method": method,
    }
    if n_points is not None:
        m["n_points"] = int(n_points)
    return m


def plane_offset_sigma(residual_m, n_points, tier):
    """Standard error of a plane's offset, floored by the tier prior. Dividing
    residual by sqrt(n) alone gives absurdly tight intervals: two million
    correlated points are not two million independent samples, so the prior is
    what stops the interval collapsing."""
    if n_points < 3:
        return TIER_PRIOR_M[tier]
    # treat only a fraction of points as independent, roughly one per 10cm patch
    eff = max(4.0, n_points / 200.0)
    return float(np.hypot(residual_m / np.sqrt(eff), TIER_PRIOR_M[tier]))


def ceiling_height(value, floor_resid, floor_n, ceil_resid, ceil_n, tier):
    s = np.hypot(plane_offset_sigma(floor_resid, floor_n, tier),
                 plane_offset_sigma(ceil_resid, ceil_n, tier))
    return measurement(value, "m", s,
                       "difference of two fitted horizontal planes, "
                       "sigma combined in quadrature with tier prior",
                       n_points=floor_n + ceil_n)


def wall_length(value, tier, cell=0.08):
    """A wall length comes off a rasterised outline, so quantisation is a real
    error source alongside the tier prior."""
    s = np.hypot(np.hypot(cell / np.sqrt(12) * 2, TIER_PRIOR_M[tier]),
                 value * TIER_PRIOR_REL[tier])
    return measurement(value, "m", s,
                       "outline edge length, raster quantisation plus tier prior")


def floor_area(value, wall_lengths, tier):
    """Area error grows with perimeter, since each boundary edge can shift."""
    perim = sum(wall_lengths) if wall_lengths else 4 * np.sqrt(max(value, 0.01))
    s = perim * np.hypot(TIER_PRIOR_M[tier], 0.08 / np.sqrt(12))
    return measurement(value, "m2", s,
                       "perimeter times boundary uncertainty")


def opening_width(value, tier, cell=0.05):
    s = np.hypot(cell / np.sqrt(12) * 2, TIER_PRIOR_M[tier] * 1.5)
    return measurement(value, "m", s,
                       "gap width on wall occupancy grid, "
                       "quantisation plus tier prior")


def coverage_report(pred, truth, level=0.90):
    """Fraction of ground-truth values that fall inside their interval. If a 90%
    interval contains truth 55% of the time the intervals are lying, and the
    case study scores calibration at every tier."""
    inside = sum(1 for p, t in zip(pred, truth)
                 if p["ci_low"] <= t <= p["ci_high"])
    widths = [p["ci_high"] - p["ci_low"] for p in pred]
    errs = [abs(p["value"] - t) for p, t in zip(pred, truth)]
    return {
        "n": len(truth),
        "nominal_level": level,
        "empirical_coverage": inside / len(truth) if truth else None,
        "mean_interval_width_m": float(np.mean(widths)) if widths else None,
        "mean_abs_error_m": float(np.mean(errs)) if errs else None,
        "max_abs_error_m": float(np.max(errs)) if errs else None,
    }
