"""
demo.py — dimostrazione end-to-end dei proiettori (tutto offline).

Uso:
    python demo.py

Nessuna rete, nessuna API, nessuna chiave: pura analisi statica.
La verifica di answer-invariance (A(x) ?= A(pi(x))) NON usa API: si fa
in-sessione dentro Claude Code / Codex con lo skill `kernel-verify`.
"""
from __future__ import annotations

from kernel_projector import PythonSlicer, EmailProjector

# --- Un modulo "sporco": il target e' compute_discount ---------------------
MESSY_CODE = '''\
import os
import sys
import json
import logging

logger = logging.getLogger(__name__)

BASE_RATE = 0.20
VIP_BONUS = 0.05


def _load_config(path):
    """Rumore: non raggiungibile da compute_discount."""
    with open(path) as f:
        return json.load(f)


def send_report(data):
    """Rumore: dead code rispetto al target."""
    logger.info("sending %s", data)
    return os.system("echo done")


def tier_multiplier(is_vip):
    return BASE_RATE + (VIP_BONUS if is_vip else 0.0)


def compute_discount(price, is_vip):
    rate = tier_multiplier(is_vip)
    return round(price * rate, 2)


class LegacyExporter:
    """Rumore: classe non collegata al target."""
    def export(self, rows):
        return sys.getsizeof(rows)
'''

QUERY = "C'e' un bug in compute_discount? Cosa restituisce?"


def demo_code() -> None:
    print("=" * 70)
    print("PROIETTORE FORMALE (codice) — backward reachability slice")
    print("=" * 70)
    print(f"Query: {QUERY}\n")

    result = PythonSlicer().project(MESSY_CODE, QUERY)
    print("Mantenuto (immagine di A):")
    for k in result.kept:
        print(f"  + {k}")
    print("\nRimosso (kernel di A):")
    for r in result.removed:
        print(f"  - {r}")
    print(f"\n{result.summary()}\n")
    print("--- pi(x) inviato all'LLM ---")
    print(result.projected)


def demo_email() -> None:
    print("=" * 70)
    print("PROIETTORE EMPIRICO (email) — firme / disclaimer / quote")
    print("=" * 70)
    email = (
        "Confermo la riunione di martedi' alle 15:00 in sala A.\n"
        "Portate il preventivo aggiornato.\n\n"
        "> Il 12/07 hai scritto:\n"
        "> possiamo vederci la prossima settimana?\n\n"
        "-- \n"
        "Mario Rossi | Head of Sales | +39 333 1234567\n"
        "CONFIDENTIAL: This email and any attachments are private.\n"
    )
    q = "Quando e' la riunione e cosa devo portare?"
    result = EmailProjector().project(email, q)
    print(f"Query: {q}\n")
    print(f"{result.summary()}\n")
    print("--- pi(x) inviato all'LLM ---")
    print(result.projected)


if __name__ == "__main__":
    demo_code()
    print()
    demo_email()
