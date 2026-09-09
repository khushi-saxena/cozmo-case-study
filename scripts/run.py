import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.ndimage import uniform_filter1d

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ingest.lidar import load_poses, unproject, voxel_downsample
from pipeline.geometry.drift import loop_closure_correction
from pipeline.geometry.outline import (wall_heading, rotation, footprint,
                                       trace_outline, simplify, snap_to_axes,
                                       drop_short_edges, merge_collinear,
                                       area, edges)
from pipeline.geometry.rooms import wall_grid, segment_rooms, adjacency
from pipeline.geometry.openings import openings_for_wall
from pipeline.render.plan import render_svg


def normals(pts, k=60, sample=200_000, seed=0):
    tree = cKDTree(pts)
    idx = (np.arange(len(pts)) if len(pts) <= sample
           else np.random.default_rng(seed).choice(len(pts), size=sample, replace=False))
    _, nb = tree.query(pts[idx], k=k)
    out = np.empty((len(idx), 3))
    for i, r in enumerate(nb):
        c = pts[r] - pts[r].mean(0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        out[i] = vt[2]
    return idx, out


def measurement(value, half_width, unit, method, n=None):
    # every number carries an interval; half_width is the 90% half-interval
    return {"value": float(value), "unit": unit,
            "ci_low": float(value - half_width), "ci_high": float(value + half_width),
            "ci_level": 0.9, "method": method,
            **({"n_points": int(n)} if n is not None else {})}


def build_cloud(capture, poses, stride, voxel):
    m = json.loads((capture / "manifest.json").read_text())
    dw, dh = m["depth_width"], m["depth_height"]
    A, used, rejected = [], 0, 0
    for p in poses[::stride]:
        if p["tracking"] != "normal":
            rejected += 1
            continue
        f = capture / f"depth/{p['index']:06d}.bin"
        if not f.exists():
            continue
        depth = np.fromfile(f, dtype=np.float32).reshape(dh, dw)
        pts, _ = unproject(depth, p["K"], p["T"], p["w"], p["h"])
        A.append(pts)
        used += 1
    pts = np.concatenate(A)
    pts, _ = voxel_downsample(pts, np.zeros(len(pts), np.uint8), voxel)
    return pts, used, rejected, m


def horizontal_planes(pts, idx, nm, camera_y):
    hp = pts[idx][np.abs(nm[:, 1]) > 0.98]
    h = hp[:, 1]
    bins = np.arange(h.min(), h.max() + 0.01, 0.01)
    hist, e = np.histogram(h, bins=bins)
    c = (e[:-1] + e[1:]) / 2
    sm = uniform_filter1d(hist.astype(float), 5)
    loc = [i for i in range(2, len(sm) - 2)
           if sm[i] == max(sm[i - 2:i + 3]) and sm[i] > 0.10 * sm.max()]
    below = [c[i] for i in loc if c[i] < camera_y - 0.4]
    above = [c[i] for i in loc if c[i] > camera_y + 0.2]
    if not below or not above:
        return None
    fl, ce = min(below), max(above)
    fb = h[np.abs(h - fl) < 0.04]
    cb = h[np.abs(h - ce) < 0.04]
    return {"floor_y": float(fl), "ceiling_y": float(ce),
            "floor_sd": float(fb.std()), "ceiling_sd": float(cb.std()),
            "floor_n": int(len(fb)), "ceiling_n": int(len(cb))}


def polygon_from_mask(mask, cell):
    o = trace_outline(mask)
    if o is None:
        return None
    poly = simplify(o, tol=0.20, cell=cell)
    poly = snap_to_axes(poly, cell=cell)
    poly = drop_short_edges(poly, 0.30)
    return merge_collinear(poly)


def run(capture, tier, out_dir, stride=4, voxel=0.03, drift_correction=True):
    t0 = time.time()
    capture = Path(capture)
    poses = load_poses(capture)
    drift_info = {"applied": False, "method": "poses used as-is"}
    if drift_correction:
        poses, drift_info = loop_closure_correction(poses)

    pts, used, rejected, manifest = build_cloud(capture, poses, stride, voxel)
    t_ingest = time.time() - t0

    idx, nm = normals(pts)
    camera_y = float(np.median([p["T"][1, 3] for p in poses]))
    planes = horizontal_planes(pts, idx, nm, camera_y)
    if planes is None:
        raise SystemExit("could not find floor and ceiling")
    fl, ce = planes["floor_y"], planes["ceiling_y"]

    theta = wall_heading(nm)
    R = rotation(theta)
    P = pts[idx]
    floor = P[(np.abs(nm[:, 1]) > 0.98) & (np.abs(P[:, 1] - fl) < 0.08)]
    grid, origin, cell = footprint(floor[:, [0, 2]] @ R.T, cell=0.08)
    if grid is None:
        raise SystemExit("floor footprint too small")

    wall_pts = P[(np.abs(nm[:, 1]) < 0.25) & (P[:, 1] > fl + 0.3) & (P[:, 1] < ce - 0.3)]
    wgrid = wall_grid(wall_pts[:, [0, 2]] @ R.T, grid.shape, origin, cell)
    rooms_lbl, n_rooms = segment_rooms(grid, wgrid, cell)

    ch_half = 1.65 * np.hypot(planes["floor_sd"], planes["ceiling_sd"])

    rooms = []
    for r in range(1, n_rooms + 1):
        mask = rooms_lbl == r
        poly = polygon_from_mask(mask, cell)
        if poly is None or len(poly) < 3:
            continue
        poly_rect = poly + origin * cell        # rectified frame, metres
        room_id = f"room_{r}"
        walls = []
        for i, L in enumerate(edges(poly_rect)):
            a, b = poly_rect[i], poly_rect[(i + 1) % len(poly_rect)]
            walls.append({
                "surface_id": f"{room_id}_wall_{i + 1}",
                "length": measurement(L, 0.10 + 0.02 * L, "m",
                                      "floor-footprint edge, 8cm raster plus 2%/m"),
                "start": [float(a[0]), float(a[1])],
                "end": [float(b[0]), float(b[1])],
            })

        ops = []
        for w in walls:
            a, b = np.array(w["start"]), np.array(w["end"])
            d = b - a
            L = np.linalg.norm(d)
            if L < 1.0:
                continue
            n2 = np.array([-d[1], d[0]]) / L
            n_world = R.T @ n2
            off = float(n_world @ (R.T @ a))
            for o in openings_for_wall(pts, n_world, off, fl, ce):
                ops.append({
                    "opening_id": f"{room_id}_opening_{len(ops) + 1}",
                    "surface_id": w["surface_id"],
                    "kind": o["kind"],
                    "width": measurement(o["width_m"], 0.05, "m", "wall occupancy gap, 5cm cells"),
                    "height": measurement(o["height_m"], 0.05, "m", "wall occupancy gap, 5cm cells"),
                    "sill_height": measurement(o["sill_height_m"], 0.05, "m", "wall occupancy gap"),
                    "centre_along_wall": o["centre_along_wall_m"],
                    "leads_to": None,
                    "detection_score": o["fill_ratio"],
                })

        A = area(poly_rect)
        rooms.append({
            "room_id": room_id,
            "polygon": [[float(x), float(y)] for x, y in poly_rect],
            "ceiling_height": measurement(ce - fl, ch_half, "m",
                                          "floor/ceiling plane separation, interval from plane scatter",
                                          planes["floor_n"] + planes["ceiling_n"]),
            "floor_area": measurement(A, 0.08 * A + 0.1, "m2", "polygon area, 8% plus raster margin"),
            "walls": walls,
            "openings": ops,
            "damage": [],
            "concealed_damage_flags": [],
        })

    total = sum(r["floor_area"]["value"] for r in rooms)
    out = {
        "capture_id": manifest["capture_id"],
        "tier": tier,
        "schema_version": "1",
        "device": {"model": manifest["device_model"],
                   "system_version": manifest["system_version"],
                   "depth_available": manifest["depth_available"]},
        "runtime": {"seconds_total": round(time.time() - t0, 2),
                    "seconds_ingest": round(t_ingest, 2),
                    "seconds_geometry": round(time.time() - t0 - t_ingest, 2),
                    "frames_used": used,
                    "frames_dropped_by_app": manifest["dropped_frames"],
                    "frames_rejected_tracking": rejected},
        "disclosure": {"models": [], "runs_offline": True},
        "rooms": rooms,
        "property": {
            "total_floor_area": measurement(total, 0.08 * total + 0.1, "m2", "sum of rooms"),
            "footprint_bbox": [float(grid.shape[0] * cell), float(grid.shape[1] * cell)],
            "adjacency": adjacency(rooms_lbl, cell),
            "drift_handling": {"method": drift_info.get("method", "none"),
                               "enabled": bool(drift_info.get("applied", False)),
                               "loop_closures": 1 if drift_info.get("applied") else 0,
                               "residual_after_closure_m": float(drift_info.get("closure_translation_m", 0.0))},
        },
        "scope_line_items": [],
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "output.json").write_text(json.dumps(out, indent=2))
    render_svg(out, out_dir / "plan.svg")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--tier", default="lidar", choices=["lidar", "video", "photo"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--no-drift-correction", action="store_true")
    a = ap.parse_args()
    out = a.out or f"benchmark/runs/{Path(a.capture).name}_{a.tier}"
    r = run(a.capture, a.tier, out, stride=a.stride, drift_correction=not a.no_drift_correction)
    print(f"{len(r['rooms'])} rooms, {r['property']['total_floor_area']['value']:.2f} m2, "
          f"ceiling {r['rooms'][0]['ceiling_height']['value']:.3f} m, "
          f"{sum(len(x['openings']) for x in r['rooms'])} openings, "
          f"{r['runtime']['seconds_total']}s -> {out}/")


if __name__ == "__main__":
    main()
