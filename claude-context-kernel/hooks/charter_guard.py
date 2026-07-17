#!/usr/bin/env python3
"""
charter_guard.py — PreToolUse hook su Edit/Write: la CARTA DEL TASK (T3)
da checklist post-hoc a INVARIANTE ATTIVO.

Quando un Edit/Write sta per toccare un file CITATO in un vincolo della
carta attiva (salvata con charter.py), il vincolo viene iniettato come
contesto PRIMA della modifica: il modello ce l'ha davanti mentre scrive,
e il verifier T4 diventa la verifica di qualcosa di gia' visto.

Conservativo: nessuna carta -> no-op; file non citato -> no-op; stesso
file gia' segnalato di recente -> no-op (dedup TTL: un refactoring lungo
sullo stesso file non deve ricevere lo stesso vincolo a ogni Edit).
Se l'harness ignorasse additionalContext su PreToolUse sarebbe un no-op
silenzioso: non blocca ne' modifica mai la chiamata. Mai fatale.
VERIFICATO DAL VIVO (2026-07-17, Claude Code): il contratto e' onorato —
i vincoli della carta arrivano al modello PRIMA dell'Edit del file citato,
e il dedup TTL evita la ripetizione al secondo Edit consecutivo.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import charter

ENABLED = os.environ.get("CK_GUARD", "1") != "0"
TTL_S = int(os.environ.get("CK_GUARD_TTL", "600"))
MAX_VINCOLI = int(os.environ.get("CK_GUARD_MAX", "8"))
STATE = os.path.expanduser(
    os.environ.get("CK_GUARD_STATE", "~/.context-kernel-guard.json"))

TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _state_load() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict):
            return st
    except Exception:                          # noqa: BLE001
        pass
    return {}


def _state_save(st: dict) -> None:
    try:
        now = time.time()
        for k in list(st):                     # scarta i record scaduti
            if now - st[k].get("ts", 0) > max(TTL_S, 3600):
                st.pop(k, None)
        for k in sorted(st, key=lambda k: st[k].get("ts", 0))[:-64]:
            st.pop(k, None)
        tmp = f"{STATE}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, STATE)
    except Exception:                          # noqa: BLE001
        pass


def already_warned(session: str, fpath: str, charter_ts: float) -> bool:
    """Stesso file, stessa carta, entro il TTL: tacere. Se la carta e' stata
    RISALVATA (ts diverso) i vincoli possono essere cambiati -> riparla."""
    key = hashlib.sha1(f"{session}|{fpath}".encode()).hexdigest()[:16]
    rec = _state_load().get(key)
    return (rec is not None and rec.get("cts") == charter_ts
            and time.time() - rec.get("ts", 0) < TTL_S)


def remember(session: str, fpath: str, charter_ts: float) -> None:
    key = hashlib.sha1(f"{session}|{fpath}".encode()).hexdigest()[:16]
    st = _state_load()
    st[key] = {"ts": time.time(), "cts": charter_ts}
    _state_save(st)


def main() -> int:
    if not ENABLED:
        print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0
    try:
        if payload.get("tool_name") not in TOOLS:
            print("{}")
            return 0
        tin = payload.get("tool_input") or {}
        fpath = tin.get("file_path") or tin.get("notebook_path")
        if not fpath:
            print("{}")
            return 0
        repo, hits = charter.constraints_for(fpath, payload.get("cwd"))
        if not hits:
            print("{}")
            return 0
        rec = charter.get_for_repo(repo) or {}
        session = (payload.get("session_id")
                   or os.path.basename(payload.get("transcript_path") or "-")[:8])
        cts = rec.get("ts", 0)
        if already_warned(session, fpath, cts):
            print("{}")
            return 0
        vincoli = "\n".join(f"- {h['vincolo']}" for h in hits[:MAX_VINCOLI])
        extra = len(hits) - MAX_VINCOLI
        if extra > 0:
            vincoli += f"\n- … altri {extra} vincoli (charter.py get)"
        ctx = ("[context-kernel] Il file che stai per modificare e' citato "
               "nella CARTA DEL TASK (T3). Vincoli che la modifica deve "
               f"rispettare:\n{vincoli}\n"
               "Dopo il fix ripassa la carta vincolo per vincolo "
               "(kernel-verifier), o rileggila con: python3 "
               f"\"{os.path.abspath(charter.__file__)}\" get --repo {repo}")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": ctx,
        }}))
        remember(session, fpath, cts)
        print(f"context-kernel[guard]: {len(hits)} vincoli per {fpath}",
              file=sys.stderr)
        return 0
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
