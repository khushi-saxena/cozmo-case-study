import json
import numpy as np
from pathlib import Path


def load_poses(capture):
    poses = []
    with open(Path(capture) / "poses.jsonl") as f:
        for line in f:
            d = json.loads(line)
            poses.append({
                "index": d["index"],
                "T": np.array(d["transform_rows"], dtype=np.float64),
                "K": np.array(d["intrinsics_rows"], dtype=np.float64),
                "w": d["image_width"],
                "h": d["image_height"],
                "tracking": d["tracking_state"],
            })
    return poses


def unproject(depth, K, T, rgb_w, rgb_h, conf=None, min_conf=None,
              z_min=0.3, z_max=5.0):
    dh, dw = depth.shape

    # intrinsics are for the full-res frame, depth map is much smaller
    sx, sy = dw / rgb_w, dh / rgb_h
    fx, fy = K[0, 0] * sx, K[1, 1] * sy
    cx, cy = K[0, 2] * sx, K[1, 2] * sy

    u, v = np.meshgrid(np.arange(dw), np.arange(dh))
    z = depth

    keep = (z > z_min) & (z < z_max)
    if conf is not None and min_conf is not None:
        keep &= conf >= min_conf
    if not keep.any():
        return np.empty((0, 3)), np.empty(0, dtype=np.uint8)

    u, v, z = u[keep], v[keep], z[keep]
    x = (u + 0.5 - cx) / fx * z
    y = (v + 0.5 - cy) / fy * z

    # ARKit looks down -Z with Y up; pinhole gives +Z forward, Y down
    pts_cam = np.stack([x, -y, -z], axis=1)
    pts_world = pts_cam @ T[:3, :3].T + T[:3, 3]

    w = conf[keep] if conf is not None else np.zeros(len(z), dtype=np.uint8)
    return pts_world, w


def voxel_downsample(pts, conf, size):
    keys = np.floor(pts / size).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    return pts[idx], conf[idx]


def build_cloud(capture, stride=4, min_conf=None, voxel=0.02):
    capture = Path(capture)
    m = json.loads((capture / "manifest.json").read_text())
    dw, dh = m["depth_width"], m["depth_height"]

    all_pts, all_conf = [], []
    for p in load_poses(capture)[::stride]:
        # poses from degraded tracking are not worth using
        if p["tracking"] != "normal":
            continue
        dfile = capture / f"depth/{p['index']:06d}.bin"
        if not dfile.exists():
            continue
        cfile = capture / f"depth/{p['index']:06d}_conf.bin"
        depth = np.fromfile(dfile, dtype=np.float32).reshape(dh, dw)
        conf = np.fromfile(cfile, dtype=np.uint8).reshape(dh, dw) if cfile.exists() else None

        pts, c = unproject(depth, p["K"], p["T"], p["w"], p["h"],
                           conf=conf, min_conf=min_conf)
        all_pts.append(pts)
        all_conf.append(c)

    pts = np.concatenate(all_pts)
    conf = np.concatenate(all_conf)
    if voxel:
        pts, conf = voxel_downsample(pts, conf, voxel)
    return pts, conf
