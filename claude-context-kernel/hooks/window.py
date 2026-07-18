#!/usr/bin/env python3
"""
window.py — l'UNICA fonte per la finestra di contesto del modello.

La stessa domanda ("quanto e' grande la finestra?") viveva risolta in TRE
punti — compact_advisor, il budget automatico dello slicer, la scala
adattiva di compress — con tre risposte non identiche (l'adattivo usava un
200k piatto; l'advisor ha detto "41%" quando il tap reale era ~13%). Qui:
un solo risolutore, tre fonti in ordine di fiducia, fonte DICHIARATA nel
ritorno cosi' chi consuma puo' dirla (il budget la stampa nel manifest).

  1. env      — CK_CONTEXT_WINDOW: l'utente sa; vince su tutto
  2. pattern  — marcatori noti nel nome modello (es. "[1m]")
  3. stima    — prudente e auto-regolante: max(200k, used*1.15+50k).
                Satura a used/win ~0.87: a finestra IGNOTA le soglie
                relative (advisor 0.70, rampa adattiva 60-90%) scattano
                solo su occupazioni grandi in assoluto — mai il contrario.

L'env si legge alla CHIAMATA (non all'import): i consumatori sono hook
lunghi una invocazione e i test variano l'ambiente per invocazione.
"""
from __future__ import annotations

import os

KNOWN_WINDOWS: tuple[tuple[str, int], ...] = (
    ("[1m]", 1_000_000),
)


def resolve_window(model: str | None, used: int) -> tuple[int, str]:
    """(finestra_in_token, fonte) — fonte in {"env", "pattern <p>", "stima"}."""
    try:
        win = int(os.environ.get("CK_CONTEXT_WINDOW", "0") or 0)
    except ValueError:
        win = 0
    if win > 0:
        return win, "env"
    m = (model or "").lower()
    for pat, w in KNOWN_WINDOWS:
        if pat in m:
            return w, f"pattern {pat}"
    return max(200_000, max(0, used) * 115 // 100 + 50_000), "stima"
