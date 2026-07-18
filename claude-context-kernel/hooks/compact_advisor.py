#!/usr/bin/env python3
"""
compact_advisor.py — PostToolUse (Bash): UNA riga quando la finestra e' piena.

Un /compact MANUALE al 70% costa meno dell'auto-compact vicino al pieno
(riassunto piu' corto, momento scelto, e lo snapshot TS(Q) del PreCompact
e' comunque pronto). Il tap dell'occupazione c'e' gia' (compress.py):
qui solo la soglia e un avviso UNA-TANTUM per sessione. Mai fatale.

Finestra: CK_CONTEXT_WINDOW, poi pattern noti sul nome modello, poi la
stessa stima prudente di auto_budget (max(200k, used*1.15+50k)) — che
satura a ~0.87, quindi a finestra ignota l'avviso scatta comunque solo
su occupazioni grandi in assoluto. CK_COMPACT_ADVISE=0 disattiva.
"""
from __future__ import annotations

import json
import os
import sys
import time

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows)
except ImportError:                        # embed per-path: stream dell'host
    pass

THRESHOLD = float(os.environ.get("CK_COMPACT_ADVISE", "0.70") or 0)
CONTEXT_STATE = os.path.expanduser(
    os.environ.get("CK_CONTEXT_STATE", "~/.context-kernel-context.json"))
ADVISE_STATE = os.path.expanduser(
    os.environ.get("CK_ADVISE_STATE", "~/.context-kernel-advised.json"))
KNOWN_WINDOWS = (("[1m]", 1_000_000),)


def session_id(transcript_path: str | None) -> str:
    if not transcript_path:
        return "-"
    base = os.path.basename(transcript_path)
    return (base[:-6] if base.endswith(".jsonl") else base)[:8] or "-"


def main() -> int:
    if THRESHOLD <= 0:
        print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0
    try:
        if payload.get("agent_id"):            # i subagent non compattano
            print("{}")
            return 0
        sid = session_id(payload.get("transcript_path"))
        with open(CONTEXT_STATE, encoding="utf-8") as f:
            rec = (json.load(f) or {}).get(sid) or {}
        used = int(rec.get("context_tokens") or 0)
        if used <= 0:
            print("{}")
            return 0
        model = rec.get("model") or "?"
        win = int(os.environ.get("CK_CONTEXT_WINDOW", "0") or 0)
        if not win:
            win = next((w for pat, w in KNOWN_WINDOWS if pat in model), 0)
        if not win:
            win = max(200_000, int(used * 1.15) + 50_000)
        if used / win < THRESHOLD:
            print("{}")
            return 0
        try:                                   # una-tantum per sessione
            with open(ADVISE_STATE, encoding="utf-8") as f:
                st = json.load(f)
            if not isinstance(st, dict):
                st = {}
        except Exception:                      # noqa: BLE001
            st = {}
        if sid in st:
            print("{}")
            return 0
        st[sid] = time.time()
        for k in sorted(st, key=lambda k: st[k])[:-16]:
            st.pop(k, None)
        tmp = f"{ADVISE_STATE}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, ADVISE_STATE)
        pct = int(used / win * 100)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"[context-kernel] finestra al {pct}% (~{used // 1000}k su "
                f"~{win // 1000}k). Un /compact MANUALE adesso costa meno "
                "dell'auto-compact vicino al pieno — e lo snapshot TS(Q) e' "
                "gia' difeso dal PreCompact. Avviso una-tantum per sessione."),
        }}))
        return 0
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
