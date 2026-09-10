"""Concealed damage rules.

Deterministic, not learned. Every flag records the rule that fired, so a
homeowner or an adjuster can see why the system thinks there is damage behind
a surface it cannot see.

Rules are written against the geometry and visible damage the pipeline already
produced, which means they are auditable in a way a model's output is not.
That is the point: the visible damage comes from perception, the inference
about what is behind the wall comes from arithmetic anyone can check.
"""

RULES = [
    {
        "rule_id": "CD-001",
        "name": "ceiling stain implies wet insulation",
        "why": "Water staining on a ceiling means water passed through the "
               "cavity above it. Insulation in that cavity is wet whether or "
               "not it is visible.",
    },
    {
        "rule_id": "CD-002",
        "name": "stain low on a wall implies wet sill plate",
        "why": "Water staining within 40 cm of the floor means water tracked "
               "down inside the wall to the base plate.",
    },
    {
        "rule_id": "CD-003",
        "name": "stain adjacent to a wet ceiling implies cavity spread",
        "why": "Staining on a wall directly under a stained ceiling means the "
               "same water path; the cavity between them is affected.",
    },
    {
        "rule_id": "CD-004",
        "name": "large stain implies substrate damage",
        "why": "Staining over 0.5 m2 on one surface means the substrate "
               "behind the finish has absorbed water, not just the finish.",
    },
]


def evaluate(rooms):
    """Run every rule against every room's damage list."""
    by_id = {r["rule_id"]: r for r in RULES}
    flags = []

    for room in rooms:
        damages = room.get("damage", [])
        ceiling_wet = [d for d in damages
                       if d["damage_class"] == "water_staining"
                       and d["surface_id"].endswith("_ceiling")]

        for d in damages:
            if d["damage_class"] != "water_staining":
                continue
            sid = d["surface_id"]
            triggered = []

            if sid.endswith("_ceiling"):
                triggered.append("CD-001")
            else:
                sill = d.get("bbox_on_surface", [0, 0, 0, 0])[1]
                if sill < 0.40:
                    triggered.append("CD-002")
                if ceiling_wet:
                    triggered.append("CD-003")

            if d["extent_m2"] > 0.5:
                triggered.append("CD-004")

            for rid in triggered:
                flags.append({
                    "flag_id": f"{room['room_id']}_flag_{len(flags) + 1}",
                    "rule_id": rid,
                    "surface_id": sid,
                    "rationale": by_id[rid]["why"],
                    "triggered_by": [d["damage_id"]],
                })
    return flags
