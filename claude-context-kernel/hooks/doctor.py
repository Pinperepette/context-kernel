#!/usr/bin/env python3
"""doctor.py — preflight deterministico dell'installazione context-kernel.

Referto a righe `[ok] / [warn] / [ko]`, veloce: i controlli strutturali sono
filesystem/versione, canary e coda A/B si leggono DIRETTAMENTE dai file di
stato (gli stessi di savings.py/ab_verify.py) senza girare l'intero report.

Nessuna dipendenza esterna. Exit 0 se non ci sono `[ko]`, 1 altrimenti — così
`/ck-doctor` e la CI possono gateare sull'esito.

Override (per i test e per installazioni non standard):
  CK_CANARY_STATE  file di stato canary  (default ~/.context-kernel-canary.json)
  CK_AB_STATE      file di stato A/B     (default ~/.context-kernel-ab.json)
"""
from __future__ import annotations

import json
import os
import sys

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows cp1252)
except ImportError:                        # embed per-path: stream dell'host, non toccarli
    pass

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(PLUGIN_ROOT, "hooks")

CANARY_STATE = os.path.expanduser(
    os.environ.get("CK_CANARY_STATE", "~/.context-kernel-canary.json"))
AB_STATE = os.path.expanduser(
    os.environ.get("CK_AB_STATE", "~/.context-kernel-ab.json"))

# Script che i comandi /ck-* wrappano: se manca uno di questi, un comando
# fallisce solo al primo uso reale. Qui lo dichiariamo subito.
CORE_SCRIPTS = [
    "compress.py", "savings.py", "ab_verify.py",
    "recall.py", "charter.py", "smoke.py",
]

# Comandi minimi della superficie scopribile.
EXPECTED_COMMANDS = [
    "ck-status", "ck-savings", "ck-verify", "ck-recall",
    "ck-charter", "ck-smoke", "ck-doctor", "ck-tune",
]


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                              # noqa: BLE001
        return None


def check():
    """Ritorna (righe, n_ko, n_warn). Riga = (livello, testo)."""
    rows = []

    def ok(msg):
        rows.append(("ok", msg))

    def warn(msg):
        rows.append(("warn", msg))

    def ko(msg):
        rows.append(("ko", msg))

    # 1. Python
    v = sys.version_info
    if v >= (3, 8):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        ko(f"Python {v.major}.{v.minor} < 3.8 richiesto")

    # 2. Hook registrati (il file vive in hooks/hooks.json; alcune installazioni
    #    lo tengono sotto .claude-plugin/ — accetta entrambe le posizioni).
    hooks_json = next(
        (p for p in (os.path.join(HOOKS, "hooks.json"),
                     os.path.join(PLUGIN_ROOT, ".claude-plugin", "hooks.json"))
         if os.path.isfile(p)), None)
    if hooks_json is None:
        ko("hooks.json assente — hook non registrati")
    else:
        try:
            with open(hooks_json, encoding="utf-8") as fh:
                body = fh.read()
        except Exception:                          # noqa: BLE001
            body = ""
        if "compress.py" in body:
            ok("hook registrati (hooks.json cita compress.py)")
        else:
            ko("hooks.json non cita compress.py — compressione non agganciata")

    # 3. Script core
    missing = [s for s in CORE_SCRIPTS if not os.path.isfile(os.path.join(HOOKS, s))]
    if missing:
        ko(f"script mancanti in hooks/: {', '.join(missing)}")
    else:
        ok(f"script core presenti ({len(CORE_SCRIPTS)})")

    # 4. MCP server
    if os.path.isfile(os.path.join(PLUGIN_ROOT, "mcp", "server.py")):
        ok("MCP server presente (mcp/server.py)")
    else:
        warn("mcp/server.py assente — gli slice via MCP non sono disponibili")

    # 5. Superficie comandi
    cmd_dir = os.path.join(PLUGIN_ROOT, "commands")
    have = set()
    if os.path.isdir(cmd_dir):
        have = {f[:-3] for f in os.listdir(cmd_dir) if f.endswith(".md")}
    miss_cmd = [c for c in EXPECTED_COMMANDS if c not in have]
    if not miss_cmd:
        ok(f"comandi /ck-* presenti ({len(EXPECTED_COMMANDS)})")
    else:
        warn(f"comandi assenti: {', '.join('/'+c for c in miss_cmd)}")

    # 5b. Superficie a linguaggio naturale (skill model-invocable)
    if os.path.isfile(os.path.join(PLUGIN_ROOT, "skills", "kernel-ops", "SKILL.md")):
        ok("superficie a linguaggio naturale presente (skill kernel-ops)")
    else:
        warn("skill kernel-ops assente — niente accesso a parole, solo /ck-*")

    # 6. Canary
    st = _load_json(CANARY_STATE)
    if st is None:
        rows.append(("--", "canary: nessuno stato ancora (plugin non ha compresso qui)"))
    else:
        failed = st.get("failed", 0)
        verified = st.get("verified", 0)
        ndeg = len(st.get("degraded_sessions", []))
        if failed:
            ko(f"canary: {failed} compressioni NON applicate dall'harness — "
               "risparmi sovrastimati (indaga, poi /ck-savings reset-canary)")
        elif ndeg:
            warn(f"canary: {ndeg} sessioni in auto-degrade (compressione sospesa)")
        else:
            ok(f"canary verde ({verified} compressioni verificate applicate)")

    # 7. Coda A/B
    ab = _load_json(AB_STATE)
    if ab is None:
        rows.append(("--", "A/B: nessuno stato ancora"))
    else:
        pend = len(ab.get("pending", []))
        if pend:
            warn(f"A/B: {pend} campioni in coda da giudicare (/ck-verify)")
        else:
            ok(f"A/B: coda vuota ({ab.get('ok', 0)} invarianti confermate)")

    n_ko = sum(1 for lvl, _ in rows if lvl == "ko")
    n_warn = sum(1 for lvl, _ in rows if lvl == "warn")
    return rows, n_ko, n_warn


_GLYPH = {"ok": "[ok]  ", "warn": "[warn]", "ko": "[ko]  ", "--": "[--]  "}


def main():
    rows, n_ko, n_warn = check()
    print("context-kernel — doctor")
    print("=" * 40)
    for lvl, msg in rows:
        print(f"  {_GLYPH.get(lvl, '[--]  ')} {msg}")
    print("-" * 40)
    if n_ko:
        print(f"  VERDETTO: {n_ko} problemi da risolvere"
              + (f", {n_warn} avvisi" if n_warn else ""))
        return 1
    if n_warn:
        print(f"  VERDETTO: installazione ok, {n_warn} avvisi (nessun bloccante)")
        return 0
    print("  VERDETTO: tutto a posto ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
