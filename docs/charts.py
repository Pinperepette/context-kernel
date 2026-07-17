#!/usr/bin/env python3
"""Genera le figure SVG del README dai dati misurati. Stdlib-only.

    python3 docs/charts.py [--ledger ~/.context-kernel-savings.log]

Due figure, ciascuna in variante light/dark (il README le monta con
<picture> + prefers-color-scheme):

  rate-sufficiency-{light,dark}.svg   barre orizzontali: riduzione del
      contesto nelle configurazioni del bench a sufficienza 100%
      (oracolo: il raise-site resta nel working set). Valori misurati,
      fonti nel README §"Numbers".
  savings-live-{light,dark}.svg       curva cumulativa dei token
      risparmiati dal ledger reale (~/.context-kernel-savings.log).

Palette: slot blu della reference palette dataviz, un solo hue per la
magnitudine; testo nei token di testo, mai nel colore della serie.
"""
from __future__ import annotations

import argparse
import datetime
import os

MODES = {
    "light": {"series": "#2a78d6", "ink": "#0b0b0b", "muted": "#52514e",
              "grid": "#d8d7d2"},
    "dark": {"series": "#3987e5", "ink": "#ffffff", "muted": "#c3c2b7",
             "grid": "#3a3a38"},
}

# Misurati (README §Numbers): riduzione % del contesto con sufficienza
# 100% all'oracolo dei raise-site. pandas 1415 file / 60 casi; lodash
# 1048 file / stack reale; T2b = discesa a livello di simbolo.
RATE_DATA = [
    ("pandas — file-level slice, full closure", 75),
    ("pandas — file-level slice, 1-hop", 91),
    ("pandas — symbol-level slice (T2b)", 96),
    ("lodash — file-level slice, real stack", 97),
]


def _text(x, y, s, size, fill, anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}" '
            f'font-family="system-ui, -apple-system, sans-serif">{s}</text>')


def rate_chart(mode: str) -> str:
    c = MODES[mode]
    W, H = 860, 300
    left, right, top = 30, 90, 92
    row_h, bar_h = 48, 16
    plot_w = W - left - right
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'role="img" aria-label="Context reduction at 100% sufficiency">']
    parts.append(_text(left, 34, "Rate at 100% sufficiency", 20, c["ink"],
                       weight="600"))
    parts.append(_text(left, 58, "context reduction per bench configuration; "
                       "the oracle keeps every real raise-site in the "
                       "working set", 13, c["muted"]))
    for i, (label, pct) in enumerate(RATE_DATA):
        y = top + i * row_h
        bw = plot_w * pct / 100.0
        parts.append(_text(left, y - 6, label, 13, c["muted"]))
        # barra: piatta alla baseline, angoli arrotondati (4px) al data-end
        parts.append(
            f'<path d="M {left} {y} h {bw - 4:.1f} q 4 0 4 4 v {bar_h - 8} '
            f'q 0 4 -4 4 h {-(bw - 4):.1f} z" fill="{c["series"]}"/>')
        parts.append(_text(left + bw + 10, y + bar_h - 3, f"−{pct}%",
                           14, c["ink"], weight="600"))
    base_y0, base_y1 = top - 4, top + len(RATE_DATA) * row_h - row_h + bar_h + 4
    parts.append(f'<line x1="{left}" y1="{base_y0}" x2="{left}" y2="{base_y1}" '
                 f'stroke="{c["grid"]}" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _read_ledger(path: str):
    pts, cum = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) < 5:
                continue
            try:
                t = datetime.datetime.fromisoformat(p[0]).timestamp()
                cum += int(p[4])
            except ValueError:
                continue
            pts.append((t, cum))
    return pts


def savings_chart(mode: str, pts) -> str:
    c = MODES[mode]
    W, H = 860, 300
    left, right, top, bottom = 30, 120, 92, 40
    plot_w, plot_h = W - left - right, H - top - bottom
    t0, t1 = pts[0][0], pts[-1][0]
    vmax = pts[-1][1]
    n = len(pts)

    def xy(t, v):
        return (left + plot_w * (t - t0) / (t1 - t0),
                top + plot_h * (1 - v / vmax))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'role="img" aria-label="Cumulative tokens saved, live sessions">']
    parts.append(_text(left, 34, "Tokens saved — live sessions", 20,
                       c["ink"], weight="600"))
    parts.append(_text(left, 58, f"cumulative, {n} compressions on one "
                       "machine doing real work (ledger: "
                       "~/.context-kernel-savings.log)", 13, c["muted"]))
    for frac in (0.5,):                        # griglia recessiva; il massimo
                                               # lo dice l'etichetta diretta
        gy = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{left + plot_w}" '
                     f'y2="{gy:.1f}" stroke="{c["grid"]}" stroke-width="1"/>')
        parts.append(_text(left + plot_w + 8, gy + 4,
                           f"{vmax * frac / 1000:,.0f}k", 12, c["muted"]))
    days, seen = [], set()
    for t, _ in pts:
        d = datetime.datetime.fromtimestamp(t).date()
        if d not in seen:
            seen.add(d)
            days.append(d)
    for d in days:
        tx = datetime.datetime.combine(d, datetime.time(12)).timestamp()
        if t0 <= tx <= t1:
            parts.append(_text(xy(tx, 0)[0], H - 14, d.strftime("%b %d"),
                               12, c["muted"], anchor="middle"))
    path = " ".join(f"{'M' if i == 0 else 'L'} {xy(t, v)[0]:.1f} "
                    f"{xy(t, v)[1]:.1f}" for i, (t, v) in enumerate(pts))
    parts.append(f'<path d="{path}" fill="none" stroke="{c["series"]}" '
                 f'stroke-width="2" stroke-linejoin="round"/>')
    ex, ey = xy(t1, vmax)
    parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" '
                 f'fill="{c["series"]}"/>')
    parts.append(_text(ex + 10, ey + 5, f"{vmax:,}", 14, c["ink"],
                       weight="600"))
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger",
                    default=os.path.expanduser("~/.context-kernel-savings.log"))
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    pts = _read_ledger(args.ledger)
    for mode in MODES:
        with open(os.path.join(args.out, f"rate-sufficiency-{mode}.svg"),
                  "w", encoding="utf-8") as f:
            f.write(rate_chart(mode))
        if pts:
            with open(os.path.join(args.out, f"savings-live-{mode}.svg"),
                      "w", encoding="utf-8") as f:
                f.write(savings_chart(mode, pts))
    print(f"figure scritte in {args.out}"
          + (f" (ledger: {len(pts)} righe)" if pts else " (nessun ledger)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
