import numpy as np
from scipy.spatial.transform import Rotation


def loop_closure_correction(poses, start_n=15, end_n=15, max_closure_m=2.0,
                            max_yaw_deg=8.0):
    """The walker comes back to where they started, but ARKit says they did
    not: the gap is accumulated drift. Spread that gap back along the path so
    the first and last poses coincide.

    This is the simplest drift handling that is not "poses used as-is". A pose
    graph with visual loop closures would do better; this one is deterministic,
    has no tunables, and runs in milliseconds, which matters for the live test.

    Returns corrected poses plus a dict describing what was done, for the
    ablation table."""
    T = np.array([p["T"] for p in poses])
    n = len(T)
    if n < start_n + end_n + 10:
        return poses, {"applied": False, "reason": "too few poses"}

    p_start = T[:start_n, :3, 3].mean(0)
    p_end = T[-end_n:, :3, 3].mean(0)
    gap = p_start - p_end
    # ARKit anchors vertical to gravity, so any vertical gap is real height
    # difference between start and end, not drift; leave it alone
    gap[1] = 0.0
    closure = float(np.linalg.norm(gap))
    if closure > max_closure_m:
        return poses, {"applied": False, "reason": f"closure {closure:.2f} m too large, "
                                                   "walker probably did not return"}

    # rotational drift: how far the final heading has turned relative to the
    # initial one, measured about the vertical axis only
    R0 = Rotation.from_matrix(T[:start_n, :3, :3]).mean().as_matrix()
    R1 = Rotation.from_matrix(T[-end_n:, :3, :3]).mean().as_matrix()
    yaw = _yaw(R0 @ R1.T)
    # the walker rarely ends facing the way they started, so a big yaw gap is
    # posture, not drift; only trust it when it is small
    yaw_applied = abs(np.degrees(yaw)) <= max_yaw_deg
    if not yaw_applied:
        yaw = 0.0

    # cumulative path length is the natural coordinate to spread error along
    seg = np.linalg.norm(np.diff(T[:, :3, 3], axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    frac = s / s[-1] if s[-1] > 0 else np.linspace(0, 1, n)

    out = []
    pivot = p_start
    for i, p in enumerate(poses):
        Ti = p["T"].copy()
        Rf = Rotation.from_rotvec([0, yaw * frac[i], 0]).as_matrix()
        # rotate about the start point, then translate
        Ti[:3, 3] = Rf @ (Ti[:3, 3] - pivot) + pivot + gap * frac[i]
        Ti[:3, :3] = Rf @ Ti[:3, :3]
        q = dict(p)
        q["T"] = Ti
        out.append(q)

    return out, {
        "applied": True,
        "method": "linear loop closure on start/end pose",
        "closure_translation_m": closure,
        "closure_yaw_deg": float(np.degrees(_yaw(R0 @ R1.T))),
        "yaw_correction_applied": bool(yaw_applied),
        "path_length_m": float(s[-1]),
    }


def _yaw(R):
    return float(np.arctan2(R[0, 2], R[2, 2]))
