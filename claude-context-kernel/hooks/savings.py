#!/usr/bin/env python3
"""
savings.py — riepiloga i token risparmiati dal compressore.

Uso:
    python3 savings.py                 # totale + breakdown per tool/sessione
    python3 savings.py --reset-canary  # riconosce i fallimenti canary storici
    CK_LOG=/path python3 savings.py    # log alternativo

Legge il CSV scritto da compress.py (default ~/.context-kernel-savings.log):
    timestamp,tool,before,after,saved[,sessione]
(la colonna sessione e' il basename corto del transcript: distingue le
compressioni di QUESTA sessione da quelle delle sessioni headless concorrenti,
es. i distiller di evolver/reforge)
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

LOG_PATH = os.path.expanduser(os.environ.get("CK_LOG", "~/.context-kernel-savings.log"))
CANARY_STATE = os.path.expanduser(
    os.environ.get("CK_CANARY_STATE", "~/.context-kernel-canary.json")
)
AB_STATE = os.path.expanduser(
    os.environ.get("CK_AB_STATE", "~/.context-kernel-ab.json")
)


def reset_canary() -> int:
    """Riconosce i fallimenti storici: failed -> failed_acked. Da usare DOPO
    averli indagati e spiegati, per non tenere l'allarme ⚠ acceso per sempre."""
    import json
    try:
        with open(CANARY_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                          # noqa: BLE001
        print("Nessuno stato canary da resettare.")
        return 0
    fl = st.get("failed", 0)
    if not fl:
        print("Nessun fallimento attivo: niente da riconoscere.")
        return 0
    st["failed_acked"] = st.get("failed_acked", 0) + fl
    st["failed"] = 0
    st["failures"] = []
    with open(CANARY_STATE, "w", encoding="utf-8") as f:
        json.dump(st, f)
    print(f"Riconosciuti {fl} fallimenti canary (storico: {st['failed_acked']}). "
          "L'allarme si riaccendera' solo su fallimenti NUOVI.")
    return 0


def canary_status() -> str | None:
    """Stato del canary end-to-end: le compressioni loggate risultano
    APPLICATE davvero (footer presente nel transcript)?"""
    try:
        import json
        with open(CANARY_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                          # noqa: BLE001
        return None
    v, fl = st.get("verified", 0), st.get("failed", 0)
    acked = st.get("failed_acked", 0)
    pend = len(st.get("pending", []))
    hist = f" ({acked} storici riconosciuti)" if acked else ""
    if fl:
        sessions = {f.get("session", "?") for f in st.get("failures", [])}
        where = f" [sessioni: {', '.join(sorted(sessions))}]" if sessions else ""
        return (f"  CANARY: ⚠ {fl} compressioni NON applicate dall'harness "
                f"(ultima: {st.get('last_failure')}){where} — risparmi sovrastimati!\n"
                f"          {v} verificate ok, {pend} in attesa{hist}\n"
                f"          (indaga, poi: python3 savings.py --reset-canary)")
    if v:
        return (f"  canary: ✓ {v} compressioni verificate applicate nel transcript "
                f"(ultima: {st.get('last_ok')}), {pend} in attesa{hist}")
    if pend:
        return f"  canary: {pend} compressioni in attesa di verifica{hist}"
    return None


def ab_status() -> str | None:
    """Ledger dell'A/B di answer-invariance (T4 campionato): il canary prova
    che la compressione e' entrata, l'A/B misura se ha preservato il segnale."""
    try:
        import json
        with open(AB_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                          # noqa: BLE001
        return None
    ok, deg = st.get("ok", 0), st.get("degraded", 0)
    pend = len(st.get("pending", []))
    if not (ok or deg or pend):
        return None
    line = f"  A/B invariance: {ok} invarianti, {deg} degradate"
    if deg:
        line = f"  A/B invariance: ⚠ {deg} degradate su {ok + deg} giudicate"
    if pend:
        line += (f", {pend} campioni in attesa "
                 f"(giudica: python3 hooks/ab_verify.py)")
    return line


def main() -> int:
    if "--reset-canary" in sys.argv[1:]:
        return reset_canary()
    if not os.path.exists(LOG_PATH):
        print(f"Nessun log ancora ({LOG_PATH}). Usa il plugin e ritorna qui.")
        return 0

    n = 0
    before_tot = after_tot = 0
    per_tool: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # before, after, count
    per_session: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # saved, count
    first = last = None

    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) not in (5, 6):       # 5 = formato storico senza sessione
                continue
            ts, tool, before, after = parts[:4]
            session = parts[5] if len(parts) == 6 else "-"
            try:
                b, a = int(before), int(after)
            except ValueError:
                continue
            n += 1
            before_tot += b
            after_tot += a
            per_tool[tool][0] += b
            per_tool[tool][1] += a
            per_tool[tool][2] += 1
            per_session[session][0] += b - a
            per_session[session][1] += 1
            first = first or ts
            last = ts

    if n == 0:
        print("Log presente ma vuoto.")
        return 0

    saved = before_tot - after_tot
    pct = saved / before_tot if before_tot else 0.0
    # stima costo input Opus 4.8: $5 / 1M token
    dollars = saved / 1_000_000 * 5.0

    print(f"context-kernel — risparmio token  ({first} -> {last})")
    print("=" * 56)
    print(f"  compressioni:      {n}")
    print(f"  token in ingresso: {before_tot:,}")
    print(f"  token dopo:        {after_tot:,}")
    print(f"  RISPARMIATI:       {saved:,}  (-{pct:.0%})")
    print(f"  ~costo input evitato (Opus 4.8, prima lettura): ${dollars:.2f}")
    print(f"  (si somma coi cache-read a ogni turno successivo)")
    print("\n  per tool:")
    for tool, (b, a, c) in sorted(per_tool.items(), key=lambda x: -(x[1][0] - x[1][1])):
        print(f"    {tool:10s}  {c:4d}x   -{b - a:,} token")

    named = {s: v for s, v in per_session.items() if s != "-"}
    if named:
        print("\n  per sessione (anche le headless concorrenti scrivono qui):")
        for sess, (sv, c) in sorted(named.items(), key=lambda x: -x[1][0])[:8]:
            print(f"    {sess:10s}  {c:4d}x   -{sv:,} token")
        if per_session.get("-"):
            sv, c = per_session["-"]
            print(f"    {'(storico)':10s}  {c:4d}x   -{sv:,} token")
    status = canary_status()
    if status:
        print()
        print(status)
    ab = ab_status()
    if ab:
        print()
        print(ab)
    return 0


if __name__ == "__main__":
    sys.exit(main())
