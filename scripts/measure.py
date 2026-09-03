import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ingest.lidar import build_cloud, load_poses
from pipeline.geometry.planes import ceiling_height


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--voxel", type=float, default=0.02)
    args = ap.parse_args()

    pts, conf = build_cloud(args.capture, stride=args.stride, voxel=args.voxel)
    poses = load_poses(args.capture)
    camera_y = float(np.median([p["T"][1, 3] for p in poses]))

    print(f"points: {len(pts):,}   camera height in world: {camera_y:+.3f} m")

    result = ceiling_height(pts, camera_y)
    if result is None:
        print("could not find horizontal planes above and below the camera")
        return
    print(json.dumps(result, indent=2))
    print(f"\nceiling height: {result['height_m']:.3f} m "
          f"({result['height_m'] / 0.3048:.2f} ft)")


if __name__ == "__main__":
    main()
