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

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows)
except ImportError:                        # embed per-path: stream dell'host, non toccarli
    pass

ENABLED = os.environ.get("CK_PRETOOL", "1") != "0"
AUTO_ALLOW = os.environ.get("CK_PRETOOL_ALLOW", "0") == "1"

# Regole: (regex che riconosce il comando, flag da garantire).
# Solo flag "quiet"/"no-progress": riducono lo stdout, non l'effetto.
#
# Ogni regola e' ancorata alla POSIZIONE DI COMANDO (inizio riga o dopo
# | ; & (, piu' eventuali VAR=val e wrapper command/sudo/time): un comando
# citato come argomento o dentro una stringa (grep "pip install", il path
# di repo_slice.py passato a grep) non deve MAI essere riscritto.
CMD_POS = (
    r"(?:^|[|;&(]\s*)"                       # inizio segmento
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"    # assegnazioni d'ambiente
    r"(?:(?:command|sudo|time)\s+)?"          # wrapper comuni
)
RULES = [
    (re.compile(CMD_POS + r"npm\s+(install|ci|i)\b"),
     ["--no-fund", "--no-audit", "--no-progress"]),
    (re.compile(CMD_POS + r"pnpm\s+(install|i|add)\b"), ["--reporter=silent"]),
    (re.compile(CMD_POS + r"pip3?\s+install\b"), ["-q"]),
    (re.compile(CMD_POS + r"yarn\s+(install|add)\b"), ["--non-interactive"]),
    # kernel repo slice senza budget esplicito: inietta il budget automatico
    # (finestra - occupato, dallo stato scritto dal PostToolUse). Il modello
    # non deve ricordarsi nulla: l'operatore costo e' ambientale.
    # Solo quando repo_slice.py e' l'ESEGUIBILE del segmento (via python o
    # diretto), mai quando il suo path e' un argomento di grep/cat/wc.
    (re.compile(
        CMD_POS + r"(?:\S*/)?python[0-9.]*\s+(?:-\S+\s+)*\S*repo_slice\.py\b"
        + r"|" + CMD_POS + r"\S*repo_slice\.py\b"), ["--budget auto"]),
]


# confine di segmento: pipe/;/&/newline, oppure una redirezione — includendo
# l'eventuale numero di fd attaccato (` 2>/dev/null`: il taglio va PRIMA del 2)
SEG_END = re.compile(r"[|;&\n]|\s\d*[><]|[><]")


def rewrite(cmd: str) -> str:
    """I flag vanno in coda al SEGMENTO che matcha, non all'intero comando:
    con una pipe (`cmd | head`) l'append cieco li darebbe al comando sbagliato."""
    if "<<" in cmd:
        # heredoc: il CORPO e' dati, non comandi — una citazione tra
        # parentesi "(.../repo_slice.py:258)" nel corpo soddisfa l'ancora
        # `(` di CMD_POS (pensata per le subshell) e lo splice salderebbe
        # le righe del documento. Osservato DUE volte sul salvataggio della
        # carta T3 (vincoli fusi + "--budget auto" nel testo): mai riscrivere.
        return cmd
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
            if rest.startswith("\n"):
                # il newline e' un confine di riga, non spazio da comprimere:
                # mangiarlo fonde la riga successiva nel segmento riscritto
                new = segment.rstrip() + add + rest
            else:
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
