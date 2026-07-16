#!/usr/bin/env python3
"""
pretool_rewrite.py — PreToolUse hook (stile RTK): riscrive il COMANDO Bash
prima dell'esecuzione perche' produca meno output, invece di comprimerlo dopo.

E' il fallback per le versioni di Claude Code che non onorano
`updatedToolOutput` del PostToolUse: qui agiamo prima, via `updatedInput`.

Approccio CONSERVATIVO: una allowlist di soli flag che riducono l'output
senza cambiare cosa fa il comando (niente semantica alterata). No-op su tutto
il resto. Non forza l'approvazione del comando (nessun `permissionDecision`)
a meno che tu non lo abiliti esplicitamente con CK_PRETOOL_ALLOW=1 — cosi'
non scavalca il gate dei permessi per default.
"""
from __future__ import annotations

import json
import os
import re
import sys

ENABLED = os.environ.get("CK_PRETOOL", "1") != "0"
AUTO_ALLOW = os.environ.get("CK_PRETOOL_ALLOW", "0") == "1"

# Regole: (regex che riconosce il comando, flag da garantire).
# Solo flag "quiet"/"no-progress": riducono lo stdout, non l'effetto.
RULES = [
    (re.compile(r"\bnpm\s+(install|ci|i)\b"), ["--no-fund", "--no-audit", "--no-progress"]),
    (re.compile(r"\bpnpm\s+(install|i|add)\b"), ["--reporter=silent"]),
    (re.compile(r"\bpip3?\s+install\b"), ["-q"]),
    (re.compile(r"\byarn\s+(install|add)\b"), ["--non-interactive"]),
    # kernel repo slice senza budget esplicito: inietta il budget automatico
    # (finestra - occupato, dallo stato scritto dal PostToolUse). Il modello
    # non deve ricordarsi nulla: l'operatore costo e' ambientale.
    (re.compile(r"\brepo_slice\.py\b"), ["--budget auto"]),
]


# confine di segmento: pipe/;/&/newline, oppure una redirezione — includendo
# l'eventuale numero di fd attaccato (` 2>/dev/null`: il taglio va PRIMA del 2)
SEG_END = re.compile(r"[|;&\n]|\s\d*[><]|[><]")


def rewrite(cmd: str) -> str:
    """I flag vanno in coda al SEGMENTO che matcha, non all'intero comando:
    con una pipe (`cmd | head`) l'append cieco li darebbe al comando sbagliato."""
    new = cmd
    for pattern, flags in RULES:
        m = pattern.search(new)
        if not m:
            continue
        endm = SEG_END.search(new, m.end())
        cut = endm.start() if endm else len(new)
        segment, rest = new[:cut], new[cut:]
        add = ""
        for flag in flags:
            base = flag.split("=")[0].split()[0]
            if base not in segment:        # idempotente: non duplica flag
                add += " " + flag
        if add:
            new = segment.rstrip() + add + (" " + rest.lstrip() if rest else "")
    return new


def main() -> int:
    if not ENABLED:
        print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:                      # noqa: BLE001
        print("{}")
        return 0

    if payload.get("tool_name") != "Bash":
        print("{}")
        return 0

    tin = payload.get("tool_input", {})
    cmd = tin.get("command", "") if isinstance(tin, dict) else ""
    if not cmd:
        print("{}")
        return 0

    new_cmd = rewrite(cmd)
    if new_cmd == cmd:
        print("{}")
        return 0

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {**tin, "command": new_cmd},
        }
    }
    if AUTO_ALLOW:
        out["hookSpecificOutput"]["permissionDecision"] = "allow"
    print(json.dumps(out))
    print(f"context-kernel[pre]: {cmd!r} -> {new_cmd!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
