"""Video tier: RGB frames plus ARKit poses, no depth files.

Monocular depth is clipped at 4 m. Past that the model is confidently wrong
indoors and sprays points metres below the real floor, which is what made
the first run's cloud span 7 m vertically against LiDAR's 3.4 m.

Depth comes from a monocular model per keyframe. The model's metric scale is
approximate, but ARKit's poses are not: when the camera moves 1 m toward a
wall, the depth to that wall should drop by 1 m. Regressing the model's
depth change against the pose's forward displacement recovers a global scale
correction with no ground truth needed."""

import json
import numpy as np
from pathlib import Path
from PIL import Image

from .lidar import load_poses, unproject, voxel_downsample
from . import monodepth


def keyframes(poses, step):
    return [p for p in poses[::step] if p["tracking"] == "normal"]


def central_depth(depth, frac=0.25):
    """Median depth of the central patch: a proxy for distance to whatever the
    camera is pointed at."""
    h, w = depth.shape
    ch, cw = int(h * frac), int(w * frac)
    patch = depth[h // 2 - ch // 2:h // 2 + ch // 2, w // 2 - cw // 2:w // 2 + cw // 2]
    return float(np.median(patch))


def scale_from_motion(frames, min_move=0.15, max_turn_deg=12.0):
    """Global scale so the model's depths agree with ARKit's metric motion.

    For consecutive keyframes that kept roughly the same heading, the change
    in central depth should equal minus the forward displacement. Ratio of
    the two is the scale; the median across pairs rejects the pairs where the
    central patch switched to a different object."""
    ratios = []
    for a, b in zip(frames[:-1], frames[1:]):
        fa = -a["T"][:3, 2]
        fb = -b["T"][:3, 2]
        turn = np.degrees(np.arccos(np.clip(fa @ fb, -1, 1)))
        if turn > max_turn_deg:
            continue
        forward_move = float((b["T"][:3, 3] - a["T"][:3, 3]) @ fa)
        if abs(forward_move) < min_move:
            continue
        d_model = b["central"] - a["central"]
        if abs(d_model) < 0.03:
            continue
        ratios.append(-forward_move / d_model)
    ratios = np.array(ratios)
    if len(ratios) < 5:
        return 1.0, {"applied": False, "reason": f"only {len(ratios)} usable pairs"}
    # only keep plausible ratios; a wild one means the patch jumped objects
    ratios = ratios[(ratios > 0.3) & (ratios < 3.0)]
    if len(ratios) < 5:
        return 1.0, {"applied": False, "reason": "no plausible pairs"}
    s = float(np.median(ratios))
    spread = float(np.percentile(ratios, 75) - np.percentile(ratios, 25))
    return s, {"applied": True, "scale": s, "iqr": spread, "pairs": int(len(ratios))}


def build_cloud(capture, stride=4, voxel=0.03, downscale=4, z_max=4.0):
    capture = Path(capture)
    poses = load_poses(capture)
    frames = keyframes(poses, stride)

    depths = []
    for p in frames:
        f = capture / f"frames/{p['index']:06d}.jpg"
        if not f.exists():
            continue
        img = Image.open(f).convert("RGB")
        if downscale > 1:
            img = img.resize((img.width // downscale, img.height // downscale), Image.BILINEAR)
        d = monodepth.predict(img)
        p["central"] = central_depth(d)
        depths.append((p, d))

    frames = [p for p, _ in depths]
    s_est, scale_info = scale_from_motion(frames)
    # the model is already metric; only override its scale when the motion
    # estimate is well supported and tight, otherwise it adds more noise than
    # it removes. either way the estimate is reported as a calibration check
    tight = (scale_info.get("applied") and scale_info["pairs"] >= 20
             and scale_info["iqr"] / max(s_est, 1e-6) < 0.15)
    s = s_est if tight else 1.0
    scale_info["used"] = bool(tight)
    scale_info["estimate"] = float(s_est)

    A = []
    for p, d in depths:
        pts, _ = unproject(d * s, p["K"], p["T"], p["w"], p["h"], z_max=z_max)
        A.append(pts)
    pts = np.concatenate(A)
    pts, _ = voxel_downsample(pts, np.zeros(len(pts), np.uint8), voxel)
    return pts, {"frames_used": len(depths), "scale_from_motion": scale_info,
                 "model": monodepth.MODEL_ID}
