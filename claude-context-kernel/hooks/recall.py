#!/usr/bin/env python3
"""
recall.py — page fault MIRATO sugli output effimeri parcheggiati.

Quando T1 elide un output Bash/MCP/WebFetch, l'originale integrale viene
parcheggiato (compress.py:park_output) e il footer dichiara la chiave.
Questo CLI recupera SOLO cio' che serve — grep o range di righe — cosi'
il fault costa i token della domanda, non dell'output intero. Nessun
ranking, nessun modello: grep e aritmetica, deterministici.

    python3 recall.py --list                     # cosa c'e' in parcheggio
    python3 recall.py KEY --grep 'ERROR|WARN'    # righe matchanti (+contesto)
    python3 recall.py KEY --lines 120-180        # range esatto
    python3 recall.py KEY --head 40              # testa
    python3 recall.py KEY --all                  # integrale (paghi tutto)

Suggerimento: aggiungi `# ck:raw` al comando per esentare l'output del
recall dalla compressione T1 (e' gia' una selezione mirata).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import zlib

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows)
except ImportError:                        # embed per-path: stream dell'host
    pass

PARK_STATE = os.path.expanduser(
    os.environ.get("CK_PARK_STATE", "~/.context-kernel-park.json"))
FAULT_LOG = os.path.expanduser(
    os.environ.get("CK_FAULT_LOG", "~/.context-kernel-faults.log"))
GREP_CONTEXT = 2
MAX_GREP_LINES = 200


def _load() -> dict:
    try:
        with open(PARK_STATE, encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except Exception:                          # noqa: BLE001
        return {}


def _text(entry: dict) -> str:
    return zlib.decompress(base64.b64decode(entry["z"])).decode(
        "utf-8", "replace")


def _log_fault(shown: str) -> None:
    """Un recall E' il pagamento di un page fault sull'output parcheggiato: ne
    registra il costo (i token EFFETTIVAMENTE restituiti — grep/lines/head
    recuperano una fetta, --all paga tutto) nel ledger dei fault, il lato
    distorsione accanto al risparmio. Mirror di compress.log_fault, tenuto
    locale per lo stesso motivo di PARK_STATE (recall non deve dipendere da
    compress). Solo numeri, mai contenuto; stesso kill-switch. Mai fatale."""
    if os.environ.get("CK_LOG_OFF") == "1":
        return
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        tok = max(0, len(shown) // 4)
        with open(FAULT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts},recall,recall,{tok},-\n")
    except Exception:                          # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("key", nargs="?", help="chiave dal footer [parcheggiato: ...]")
    ap.add_argument("--grep", metavar="REGEX")
    ap.add_argument("-C", "--context", type=int, default=GREP_CONTEXT)
    ap.add_argument("--lines", metavar="A-B")
    ap.add_argument("--head", type=int, metavar="N")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    st = _load()
    if args.list or not args.key:
        if not st:
            print("parcheggio vuoto")
            return 0
        now = time.time()
        for k, e in sorted(st.items(), key=lambda kv: -kv[1].get("ts", 0)):
            age = int((now - e.get("ts", now)) / 60)
            trunc = " [TRONCATO al parcheggio]" if e.get("trunc") else ""
            print(f"{k}  {e.get('tool', '?'):<10} {age:>4}min fa  "
                  f"{e.get('cmd', '')[:80]}{trunc}")
        return 0

    entry = st.get(args.key)
    if not entry:
        print(f"chiave '{args.key}' assente o scaduta (TTL). "
              "`--list` per vedere il parcheggio.", file=sys.stderr)
        return 2
    lines = _text(entry).split("\n")
    if entry.get("trunc"):
        print("# NOTA: originale TRONCATO al parcheggio (oltre il cap)",
              file=sys.stderr)

    if args.grep:
        try:
            rx = re.compile(args.grep)
        except re.error as e:
            print(f"regex non valida: {e}", file=sys.stderr)
            return 2
        hit_idx = [i for i, ln in enumerate(lines) if rx.search(ln)]
        if not hit_idx:
            print(f"nessuna riga matcha /{args.grep}/ "
                  f"({len(lines)} righe parcheggiate)")
            return 0
        keep: set[int] = set()
        for i in hit_idx:
            keep.update(range(max(0, i - args.context),
                              min(len(lines), i + args.context + 1)))
        out: list[str] = []
        shown = 0
        last = -2
        for i in sorted(keep):
            if shown >= MAX_GREP_LINES:
                out.append(f"… altri match oltre il cap di {MAX_GREP_LINES} "
                           "righe (restringi la regex o usa --lines)")
                break
            if i != last + 1:
                out.append("…")
            out.append(f"{i + 1}\t{lines[i]}")
            last = i
            shown += 1
        text = "\n".join(out)
        print(text)
        _log_fault(text)
        return 0

    if args.lines:
        m = re.fullmatch(r"(\d+)-(\d+)", args.lines.strip())
        if not m:
            print("--lines vuole il formato A-B (1-based)", file=sys.stderr)
            return 2
        a, b = int(m.group(1)), int(m.group(2))
        out = [f"{i}\t{lines[i - 1]}"
               for i in range(max(1, a), min(len(lines), b) + 1)]
        text = "\n".join(out)
        print(text)
        _log_fault(text)
        return 0

    if args.all:
        text = "\n".join(lines)
        print(text)
        _log_fault(text)
        return 0

    n = args.head or 40
    out = [f"{i + 1}\t{lines[i]}" for i in range(min(n, len(lines)))]
    if len(lines) > n:
        out.append(f"… {len(lines) - n} righe restanti "
                   "(--grep, --lines A-B, oppure --all per l'integrale)")
    text = "\n".join(out)
    print(text)
    _log_fault(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
