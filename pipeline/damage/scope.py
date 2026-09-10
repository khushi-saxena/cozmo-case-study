"""Turn damage into repair line items.

Deterministic arithmetic on the damage extents the pipeline measured. No
pricing - quantities and units only, keyed to the surface they came from, so
whatever estimating system consumes this can apply its own rates.

Waste factors are the conventional trade allowances: 10% on sheet goods, 5%
on paint.
"""

LINE_ITEMS = {
    "water_staining": [
        ("remove and replace drywall", "m2", 1.10),
        ("seal and prime stained substrate", "m2", 1.05),
        ("paint to match, two coats", "m2", 1.05),
    ],
    "burn_or_hole": [
        ("cut out and patch substrate", "m2", 1.10),
        ("skim and sand patch", "m2", 1.05),
        ("paint to match, two coats", "m2", 1.05),
    ],
    "surface_discolouration": [
        ("clean and prepare surface", "m2", 1.00),
        ("paint to match, two coats", "m2", 1.05),
    ],
}

CONCEALED_ITEMS = {
    "CD-001": ("remove and replace wet ceiling insulation", "m2", 1.10),
    "CD-002": ("expose and dry sill plate", "m", 1.00),
    "CD-003": ("open wall cavity for drying", "m2", 1.00),
    "CD-004": ("replace substrate behind finish", "m2", 1.10),
}


def build(rooms, flags):
    items = []

    for room in rooms:
        for d in room.get("damage", []):
            area = d["extent_m2"]["value"] if isinstance(d["extent_m2"], dict) else d["extent_m2"]
            for desc, unit, waste in LINE_ITEMS.get(d["damage_class"], []):
                q = area * waste
                items.append({
                    "line_item_id": f"LI-{len(items) + 1:03d}",
                    "surface_id": d["surface_id"],
                    "damage_id": d["damage_id"],
                    "description": desc,
                    "quantity": {"value": round(q, 3), "unit": unit,
                                 "ci_low": round(q * 0.8, 3), "ci_high": round(q * 1.25, 3),
                                 "ci_level": 0.9,
                                 "method": f"measured extent x {waste} waste factor"},
                    "unit": unit,
                })

    for f in flags:
        spec = CONCEALED_ITEMS.get(f["rule_id"])
        if not spec:
            continue
        desc, unit, waste = spec
        items.append({
            "line_item_id": f"LI-{len(items) + 1:03d}",
            "surface_id": f["surface_id"],
            "damage_id": None,
            "description": desc + f" (concealed, rule {f['rule_id']})",
            "quantity": {"value": 0.0, "unit": unit,
                         "ci_low": 0.0, "ci_high": 0.0, "ci_level": 0.9,
                         "method": "extent unknown until the surface is opened"},
            "unit": unit,
        })

    return items
