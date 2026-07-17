#!/usr/bin/env python3
"""
session_brief.py — SessionStart hook: UNA riga di consapevolezza (~40 token).

T1 e' invisibile per design, ma un modello che SA di vivere in un ambiente
compresso ne usa i meccanismi (page fault, slice ambientale) invece di
subirli: senza questo brief e' capitato che il modello giudicasse il plugin
"mai usato" mentre gli aveva risparmiato 277k token. Mai fatale.
"""
from __future__ import annotations

import json
import os
import sys

ENABLED = os.environ.get("CK_BRIEF", "1") != "0"
LOG_PATH = os.path.expanduser(
    os.environ.get("CK_LOG", "~/.context-kernel-savings.log"))
AB_STATE = os.path.expanduser(
    os.environ.get("CK_AB_STATE", "~/.context-kernel-ab.json"))
# Snapshot TS(Q) scritto da precompact_snapshot.py: alla SessionStart con
# source=="compact" viene reiniettato qui — la sessione post-compact riparte
# col task state (carta T3 + working set T2), non col solo riassunto.
COMPACT_STATE = os.path.expanduser(
    os.environ.get("CK_COMPACT_STATE", "~/.context-kernel-compact.json"))
COMPACT_MAX_AGE_S = int(os.environ.get("CK_COMPACT_MAX_AGE", "1800"))


def savings_line() -> str:
    """Totale storico dal ledger CSV (ts,tool,before,after,saved,session)."""
    try:
        n = saved = 0
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 5:
                    n += 1
                    saved += int(parts[4])
        if n:
            return f" Finora: {n} compressioni, ~{saved:,} token risparmiati."
    except Exception:                          # noqa: BLE001
        pass
    return ""


def ab_line() -> str:
    """Promemoria: campioni A/B fermi in attesa del giudizio. ab_verify.py e'
    manuale (o cron): senza questa riga i campioni restano li' per sempre."""
    try:
        with open(AB_STATE, encoding="utf-8") as f:
            n = len(json.load(f).get("pending") or [])
        if n:
            root = (os.environ.get("CLAUDE_PLUGIN_ROOT")
                    or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            return (f" A/B: {n} campioni in attesa di giudizio — `python3 "
                    f"{os.path.join(root, 'hooks', 'ab_verify.py')}`.")
    except Exception:                          # noqa: BLE001
        pass
    return ""


def compact_restore(payload: dict) -> str:
    """TS(Q) fotografato da precompact_snapshot.py: se questa SessionStart
    viene da una compaction, riportalo nel contesto. Vuoto se non c'e' nulla
    (o lo snapshot e' vecchio: un'altra faccenda, non questo task)."""
    try:
        import time
        with open(COMPACT_STATE, encoding="utf-8") as f:
            st = json.load(f)
        session = (payload.get("session_id")
                   or os.path.basename(payload.get("transcript_path") or "-")[:8])
        rec = st.get(session)
        if not rec:                            # fallback: lo snapshot piu' recente
            rec = max(st.values(), key=lambda r: r.get("ts", 0), default=None)
        if not rec or time.time() - rec.get("ts", 0) > COMPACT_MAX_AGE_S:
            return ""
        parts = ["\n[context-kernel] TS(Q) sopravvissuto alla compaction — "
                 "il riassunto e' una proiezione NON indicizzata dal task; "
                 "questo e' lo stato del task fotografato prima:"]
        if rec.get("charter_head"):
            parts.append("--- carta del task (T3) attiva ---\n"
                         + rec["charter_head"])
        if rec.get("slice_head"):
            parts.append("--- working set (T2) attivo ---\n"
                         + rec["slice_head"])
        return "\n".join(parts)
    except Exception:                          # noqa: BLE001
        return ""


def main() -> int:
    if not ENABLED:
        print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)         # contratto: JSON su stdin
        if not isinstance(payload, dict):
            payload = {}
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0
    ctx = (
        "[context-kernel] attivo: gli output lunghi dei tool arrivano "
        "compressi (footer `[context-kernel: ...]`). Page fault: se una Read "
        "arriva ELISA o marcata INVARIATO, rileggere lo stesso file la fa "
        "passare integrale. Per bug con sintomo concreto c'e' la skill "
        "kernel-repo-slice (T2); con un traceback nel prompt la slice viene "
        "iniettata da sola." + savings_line() + ab_line()
    )
    if payload.get("source") == "compact":
        ctx += compact_restore(payload)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
