#!/usr/bin/env python3
"""
symptom_slice.py — UserPromptSubmit hook: T2 AMBIENTALE.

Se il prompt dell'utente contiene un SINTOMO concreto (traceback, errore con
coordinate file:riga), esegue lo slicer deterministico del repository (T2,
cachato) e inietta la testa del manifest come contesto aggiuntivo: il modello
si trova il working set davanti senza doversi ricordare della skill — lo
stesso principio del budget automatico (l'operatore di costo e' ambientale).

Conservativo: nessun sintomo forte -> no-op; repo piccolo -> no-op (si legge
e basta); slicer lento o rotto -> no-op. Mai fatale: su qualsiasi imprevisto
stampa "{}" ed esce 0.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ENABLED = os.environ.get("CK_SYMPTOM", "1") != "0"
MIN_FILES = int(os.environ.get("CK_SYMPTOM_MIN_FILES", "50"))
TIMEOUT = float(os.environ.get("CK_SYMPTOM_TIMEOUT", "10"))
MAX_LINES = int(os.environ.get("CK_SYMPTOM_MAX_LINES", "40"))

# Sintomi FORTI: un traceback vero o un errore con coordinate file:riga.
# Meglio un falso negativo che iniettare rumore su un prompt qualunque.
STRONG = [
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r'File "[^"]+", line \d+'),
    re.compile(r"^\s*at .+\(.+:\d+:\d+\)", re.MULTILINE),  # stack JS/TS
    re.compile(r"\b\w+(?:Error|Exception)\b\s*:"),
    re.compile(r"\bpanic(?::| at)\s"),
    re.compile(r"\b[\w/.-]+\.(?:py|js|jsx|ts|tsx|go|rs|rb|java|c|cc|cpp):\d+\b"),
]

CODE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
             ".java", ".rb", ".c", ".cc", ".cpp", ".cs", ".php", ".swift")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
             "dist", "build", ".next", "vendor", ".tox", "target"}


def has_symptom(prompt: str) -> bool:
    return any(rx.search(prompt) for rx in STRONG)


def repo_big_enough(root: str) -> bool:
    """Sotto MIN_FILES sorgenti la slice non paga: si legge e basta
    (stessa soglia documentata nella skill kernel-repo-slice)."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            if f.endswith(CODE_EXTS):
                count += 1
                if count >= MIN_FILES:
                    return True
    return False


def slicer_path() -> str:
    plugin_root = (os.environ.get("CLAUDE_PLUGIN_ROOT")
                   or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(plugin_root, "skills", "kernel-repo-slice",
                        "scripts", "repo_slice.py")


def main() -> int:
    if not ENABLED:
        print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0

    prompt = payload.get("prompt") or ""
    cwd = payload.get("cwd") or os.getcwd()
    # slash command, o pilotaggio manuale gia' in corso: non intrometterti
    if (not prompt or prompt.lstrip().startswith("/")
            or "kernel-repo-slice" in prompt or "repo_slice" in prompt):
        print("{}")
        return 0

    try:
        if (not has_symptom(prompt) or not os.path.isdir(cwd)
                or not repo_big_enough(cwd)):
            print("{}")
            return 0
        proc = subprocess.run(
            [sys.executable, slicer_path(), cwd,
             "--symptom", prompt[:8000], "--budget", "auto"],
            capture_output=True, text=True, timeout=TIMEOUT)
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 or "## seed" not in out:
            print("{}")                        # niente seed: meglio tacere
            return 0
        head = "\n".join(out.split("\n")[:MAX_LINES])
        ctx = ("[context-kernel] Sintomo rilevato nel prompt: working set "
               "calcolato dallo slicer deterministico (T2). Usalo come prior "
               "per l'esplorazione, non come divieto; per rifarlo con altri "
               "parametri c'e' la skill kernel-repo-slice.\n" + head)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ctx,
        }}))
        print(f"context-kernel[symptom]: slice iniettata da {cwd}",
              file=sys.stderr)
        return 0
    except Exception:                          # noqa: BLE001
        print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
