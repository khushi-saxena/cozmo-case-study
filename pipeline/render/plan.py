"""Draw the plan as SVG. Nothing fancy: rooms, wall lengths, openings."""


def render_svg(out, path, scale=80, pad=40):
    rooms = out["rooms"]
    if not rooms:
        return
    xs = [p[0] for r in rooms for p in r["polygon"]]
    ys = [p[1] for r in rooms for p in r["polygon"]]
    x0, y0 = min(xs), min(ys)
    W = int((max(xs) - x0) * scale + 2 * pad)
    H = int((max(ys) - y0) * scale + 2 * pad)

    def X(x): return pad + (x - x0) * scale
    def Y(y): return pad + (y - y0) * scale

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="Helvetica, Arial" font-size="11">',
         '<rect width="100%" height="100%" fill="white"/>']
    for r in rooms:
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in r["polygon"])
        s.append(f'<polygon points="{pts}" fill="#f4f1ea" stroke="#333" stroke-width="2"/>')
        cx = sum(p[0] for p in r["polygon"]) / len(r["polygon"])
        cy = sum(p[1] for p in r["polygon"]) / len(r["polygon"])
        s.append(f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" text-anchor="middle" font-weight="bold">'
                 f'{r["room_id"]}</text>')
        s.append(f'<text x="{X(cx):.1f}" y="{Y(cy) + 14:.1f}" text-anchor="middle" fill="#555">'
                 f'{r["floor_area"]["value"]:.1f} m² · h {r["ceiling_height"]["value"]:.2f} m</text>')
        for w in r["walls"]:
            (ax, ay), (bx, by) = w["start"], w["end"]
            L = w["length"]["value"]
            if L < 0.6:
                continue
            mx, my = (ax + bx) / 2, (ay + by) / 2
            s.append(f'<text x="{X(mx):.1f}" y="{Y(my) - 4:.1f}" text-anchor="middle" '
                     f'fill="#1a5fb4" font-size="10">{L:.2f}</text>')
        for o in r["openings"]:
            w = next(x for x in r["walls"] if x["surface_id"] == o["surface_id"])
            (ax, ay), (bx, by) = w["start"], w["end"]
            L = w["length"]["value"]
            t = o["centre_along_wall"]
            # place a tick at the fractional position along the wall
            # (centre_along_wall is in the wall's own frame; use its length ratio)
            frac = min(max((t - min(0, t)) / L, 0.05), 0.95) if L > 0 else 0.5
            px, py = ax + (bx - ax) * frac, ay + (by - ay) * frac
            col = "#c01c28" if o["kind"] == "door" else "#2ec27e"
            s.append(f'<circle cx="{X(px):.1f}" cy="{Y(py):.1f}" r="5" fill="{col}"/>')
            s.append(f'<text x="{X(px) + 7:.1f}" y="{Y(py) + 4:.1f}" font-size="9" fill="{col}">'
                     f'{o["kind"]} {o["width"]["value"]:.2f}</text>')
    s.append(f'<text x="{pad}" y="{H - 12}" fill="#777" font-size="10">'
             f'{out["capture_id"]} · tier {out["tier"]} · {out["runtime"]["seconds_total"]}s</text>')
    s.append("</svg>")
    path.write_text("\n".join(s))
