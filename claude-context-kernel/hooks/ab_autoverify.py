#!/usr/bin/env python3
"""
ab_autoverify.py — hook SessionStart: smaltisce i campioni A/B in coda da solo,
"ogni tanto", senza umano nel loop e senza bloccare l'avvio.

Meccanica: se i campioni in attesa sono >= soglia E l'ultimo lancio automatico
e' piu' vecchio dell'intervallo, fa partire ab_verify.py in BACKGROUND
(processo scollegato, start_new_session): i giudizi via `claude -p` avvengono
a parte, l'avvio della sessione non aspetta nulla. Il conteggio "A/B: N in
attesa" della statusline cala da solo alla tornata successiva.

Freno (default: >= 8 in coda, al massimo 1 tornata / 24h, 5 giudizi a tornata).
Lo stamp viene scritto PRIMA di lanciare: due sessioni aperte insieme non
avviano due tornate.

Config (env):
  CK_AB_AUTO         "0" per spegnere del tutto            (default acceso)
  CK_AB_AUTO_MIN     campioni minimi in coda per scattare  (default 8)
  CK_AB_AUTO_EVERY   ore minime tra due tornate            (default 24)
  CK_AB_AUTO_LIMIT   giudizi max per tornata               (default 5)
  CK_AB_STATE        stato campioni/ledger  (default ~/.context-kernel-ab.json)

READ-ONLY sullo stato del plugin: non tocca ~/.context-kernel-ab.json (lo fa
ab_verify), scrive solo il proprio stamp e il proprio log.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows)
except ImportError:                        # embed per-path: stream dell'host
    pass

AB_STATE = os.path.expanduser(
    os.environ.get("CK_AB_STATE", "~/.context-kernel-ab.json")
)
STAMP = os.path.expanduser("~/.context-kernel-ab-auto.stamp")
LOG = os.path.expanduser("~/.context-kernel-ab-auto.log")

MIN_PENDING = int(os.environ.get("CK_AB_AUTO_MIN", "8"))
EVERY_HOURS = float(os.environ.get("CK_AB_AUTO_EVERY", "24"))
LIMIT = int(os.environ.get("CK_AB_AUTO_LIMIT", "5"))


def _pending_count() -> int:
    """Quanti campioni A/B aspettano un giudizio. 0 se lo stato manca o e'
    illeggibile — nel dubbio non si scatta."""
    try:
        with open(AB_STATE, encoding="utf-8") as f:
            st = json.load(f)
        pend = st.get("pending", []) if isinstance(st, dict) else []
        return len(pend) if isinstance(pend, list) else 0
    except Exception:                          # noqa: BLE001
        return 0


def _hours_since_last() -> float:
    """Ore dall'ultima tornata automatica. Infinito se non c'e' stamp valido
    (mai lanciato -> il tempo non frena)."""
    try:
        with open(STAMP, encoding="utf-8") as f:
            prev = datetime.datetime.fromisoformat(f.read().strip())
        delta = datetime.datetime.now() - prev
        return delta.total_seconds() / 3600.0
    except Exception:                          # noqa: BLE001
        return float("inf")


def _touch_stamp() -> None:
    tmp = f"{STAMP}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now().isoformat())
    os.replace(tmp, STAMP)


def main() -> int:
    # SessionStart passa un payload JSON su stdin: lo consumiamo e ignoriamo.
    try:
        sys.stdin.read()
    except Exception:                          # noqa: BLE001
        pass

    if os.environ.get("CK_AB_AUTO", "1") == "0":
        return 0

    pending = _pending_count()
    if pending < MIN_PENDING:
        return 0
    if _hours_since_last() < EVERY_HOURS:
        return 0

    # Lo stamp PRIMA del lancio: gate contro tornate doppie da sessioni
    # concorrenti, e non ritenta a raffica se il lancio fallisce.
    _touch_stamp()

    verifier = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "ab_verify.py")
    try:
        logf = open(LOG, "a", encoding="utf-8")
    except Exception:                          # noqa: BLE001
        logf = subprocess.DEVNULL
    try:
        logf.write(
            f"\n=== {datetime.datetime.now().isoformat()} "
            f"auto-run: {pending} in coda, limit {LIMIT} ===\n")
        logf.flush()
    except Exception:                          # noqa: BLE001
        pass

    # Fire-and-forget: processo scollegato, l'avvio della sessione non aspetta
    # i giudizi (ognuno fino a CK_AB_TIMEOUT).
    try:
        subprocess.Popen(
            [sys.executable, verifier, "--limit", str(LIMIT)],
            stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
            start_new_session=True,
        )
    except Exception:                          # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
