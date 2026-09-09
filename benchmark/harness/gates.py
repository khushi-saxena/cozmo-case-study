"""Score every run in benchmark/runs against the gates and the ground truth.

Reads the ground truth CSV, walks the run outputs, and writes the gate table,
the repeatability table and the head-to-head table. Nothing here recomputes
geometry - it only compares what the pipeline already wrote, so the numbers in
the report and the numbers in the JSON cannot drift apart.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

GATES = {
    "ceiling_height_cm": 1.5,
    "ceiling_spread_cm": 1.0,
    "opening_width_cm": 2.0,
    "opening_pass_rate": 0.85,
    "repeatability_wall_cm": 1.0,
    "repeatability_wall_pct": 0.5,
    "photo_wall_pct": 8.0,
    "video_wall_pct": 3.0,
    "photo_footprint_pct": 8.0,
}


def load_truth(path):
    truth = {}
    if not Path(path).exists():
        return truth
    with open(path) as f:
        for row in csv.DictReader(f):
            key = (row.get("room_id", ""), row.get("surface_id", ""), row["type"])
            vals = [row.get("pass_1_cm"), row.get("pass_2_cm")]
            vals = [float(v) for v in vals if v not in (None, "", "TODO")]
            if vals:
                truth[key] = {"mean": sum(vals) / len(vals),
                              "spread": max(vals) - min(vals) if len(vals) > 1 else None,
                              "n_passes": len(vals)}
    return truth


def load_runs(runs_dir):
    out = {}
    for d in sorted(Path(runs_dir).iterdir()):
        f = d / "output.json"
        if f.exists():
            out[d.name] = json.loads(f.read_text())
    return out


def ceiling_rows(runs, truth):
    gt = truth.get(("room_01", "", "ceiling_height"))
    rows = []
    for name, o in runs.items():
        for r in o["rooms"]:
            v = r["ceiling_height"]["value"] * 100
            lo = r["ceiling_height"]["ci_low"] * 100
            hi = r["ceiling_height"]["ci_high"] * 100
            row = {"run": name, "tier": o["tier"], "room": r["room_id"],
                   "value_cm": round(v, 1),
                   "ci_cm": f"[{lo:.1f}, {hi:.1f}]"}
            if gt:
                err = v - gt["mean"]
                row["truth_cm"] = round(gt["mean"], 1)
                row["error_cm"] = round(err, 1)
                row["gate_1_5cm"] = "pass" if abs(err) <= GATES["ceiling_height_cm"] else "FAIL"
                row["truth_covered_by_ci"] = "yes" if lo <= gt["mean"] <= hi else "no"
            rows.append(row)
    return rows


def repeatability(runs, a, b):
    if a not in runs or b not in runs:
        return None
    ca = runs[a]["rooms"][0]["ceiling_height"]["value"] * 100
    cb = runs[b]["rooms"][0]["ceiling_height"]["value"] * 100
    return {"run_a": a, "run_b": b,
            "ceiling_a_cm": round(ca, 1), "ceiling_b_cm": round(cb, 1),
            "spread_cm": round(abs(ca - cb), 2),
            "gate_1cm": "pass" if abs(ca - cb) <= GATES["ceiling_spread_cm"] else "FAIL"}


def openings(runs, truth_openings):
    rows = []
    for name, o in runs.items():
        found = [x for r in o["rooms"] for x in r["openings"]]
        kinds = {}
        for x in found:
            kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
        rows.append({"run": name, "tier": o["tier"],
                     "detected": len(found),
                     "real_in_room": truth_openings,
                     "by_kind": kinds,
                     "widths_m": [round(x["width"]["value"], 2) for x in found]})
    return rows


def tier_comparison(runs, reference):
    if reference not in runs:
        return []
    ref = runs[reference]
    ref_area = ref["property"]["total_floor_area"]["value"]
    ref_ceil = ref["rooms"][0]["ceiling_height"]["value"]
    rows = []
    for name, o in runs.items():
        a = o["property"]["total_floor_area"]["value"]
        c = o["rooms"][0]["ceiling_height"]["value"]
        rows.append({"run": name, "tier": o["tier"],
                     "area_m2": round(a, 2),
                     "area_vs_lidar_pct": round(100 * (a - ref_area) / ref_area, 1),
                     "ceiling_m": round(c, 3),
                     "ceiling_vs_lidar_pct": round(100 * (c - ref_ceil) / ref_ceil, 1),
                     "runtime_s": o["runtime"]["seconds_total"],
                     "rooms": len(o["rooms"])})
    return rows


def head_to_head(runs, incumbent_csv, our_run):
    if not Path(incumbent_csv).exists() or our_run not in runs:
        return []
    inc = {}
    with open(incumbent_csv) as f:
        for row in csv.DictReader(f):
            try:
                inc[row["metric"]] = float(row["magicplan_value"])
            except (ValueError, KeyError):
                pass
    o = runs[our_run]
    rows = []
    ours_ceiling = o["rooms"][0]["ceiling_height"]["value"]
    if "ceiling_height" in inc:
        rows.append({"dimension": "ceiling_height_m",
                     "ours": round(ours_ceiling, 3),
                     "incumbent": inc["ceiling_height"],
                     "diff_cm": round((ours_ceiling - inc["ceiling_height"]) * 100, 1)})
    ours_area = o["property"]["total_floor_area"]["value"]
    if "floor_area_without_walls" in inc:
        rows.append({"dimension": "floor_area_m2",
                     "ours": round(ours_area, 2),
                     "incumbent": inc["floor_area_without_walls"],
                     "diff_pct": round(100 * (ours_area - inc["floor_area_without_walls"])
                                       / inc["floor_area_without_walls"], 1)})
    return rows


def main():
    runs = load_runs(ROOT / "benchmark/runs")
    truth = load_truth(ROOT / "benchmark/ground_truth/room_01.csv")

    report = {
        "gates": GATES,
        "ceiling_height": ceiling_rows(runs, truth),
        "repeatability": repeatability(runs, "repeat_a", "repeat_b"),
        "openings": openings(runs, truth_openings=3),
        "tiers": tier_comparison(runs, "capture_1788930419_lidar"),
        "head_to_head": head_to_head(
            runs, ROOT / "benchmark/incumbent/magicplan_room_01.csv",
            "capture_1788930419_lidar"),
    }

    out = ROOT / "benchmark/harness/gate_report.json"
    out.write_text(json.dumps(report, indent=2))

    print("=== ceiling height")
    for r in report["ceiling_height"]:
        print("  %-38s %-6s %7.1f cm  ci %s  %s" %
              (r["run"], r["tier"], r["value_cm"], r["ci_cm"],
               r.get("gate_1_5cm", "no truth")))

    if report["repeatability"]:
        rp = report["repeatability"]
        print("\n=== repeatability (same room, two captures)")
        print("  %.1f vs %.1f cm  spread %.2f cm  gate 1cm: %s" %
              (rp["ceiling_a_cm"], rp["ceiling_b_cm"], rp["spread_cm"], rp["gate_1cm"]))

    print("\n=== openings (3 real in room_01)")
    for r in report["openings"]:
        print("  %-38s %-6s detected %d  %s" %
              (r["run"], r["tier"], r["detected"], r["by_kind"]))

    print("\n=== tiers vs lidar")
    for r in report["tiers"]:
        print("  %-38s %-6s area %6.2f (%+6.1f%%)  ceiling %.3f (%+5.1f%%)  %5.1fs" %
              (r["run"], r["tier"], r["area_m2"], r["area_vs_lidar_pct"],
               r["ceiling_m"], r["ceiling_vs_lidar_pct"], r["runtime_s"]))

    print("\n=== head to head vs magicplan 2026.35.0")
    for r in report["head_to_head"]:
        extra = r.get("diff_cm", r.get("diff_pct"))
        print("  %-20s ours %8.3f  theirs %8.3f  diff %s" %
              (r["dimension"], r["ours"], r["incumbent"], extra))

    print("\nwrote %s" % out.relative_to(ROOT))


if __name__ == "__main__":
    main()
