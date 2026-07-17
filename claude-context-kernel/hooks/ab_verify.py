#!/usr/bin/env python3
"""
ab_verify.py — giudizio A/B di answer-invariance sui campioni di elisione
(T4 campionato sul traffico reale).

compress.py campiona 1 elisione ogni CK_AB_RATE (default 20) salvando la coppia
(originale, compresso) in ~/.context-kernel-ab.json. Questo tool fa giudicare
ogni coppia a un modello via `claude -p` (headless: usa l'abbonamento, zero
chiavi API): la versione compressa conserva TUTTI i segnali azionabili
dell'originale? Il verdetto aggiorna il ledger che savings.py riporta.

Uso:
    python3 ab_verify.py               # giudica i campioni in attesa
    python3 ab_verify.py --limit 3     # al massimo 3 giudizi
    python3 ab_verify.py --status      # solo il riepilogo, nessuna chiamata
    python3 ab_verify.py --dry-run     # stampa i prompt, nessuna chiamata
    python3 ab_verify.py --cron        # stampa la riga crontab pronta
                                       # (non installa nulla da sola)

Ambiente:
    CK_AB_STATE    stato campioni/ledger (default ~/.context-kernel-ab.json)
    CK_AB_CLAUDE   binario del giudice   (default: claude)
    CK_AB_MODEL    modello del giudice   (default: quello di `claude -p`)
    CK_AB_TIMEOUT  timeout per giudizio in secondi (default 180)

Contratto col giudice: l'ULTIMA riga della sua risposta deve essere
    VERDETTO: INVARIANTE
oppure
    VERDETTO: DEGRADATO — <i segnali persi>
Risposte non parsabili lasciano il campione in attesa (max 3 tentativi).
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import shutil
import subprocess
import sys
import zlib

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows)
except ImportError:                        # embed per-path: stream dell'host, non toccarli
    pass

AB_STATE = os.path.expanduser(
    os.environ.get("CK_AB_STATE", "~/.context-kernel-ab.json")
)
# which() risolve anche gli shim Windows (claude.cmd), che subprocess.run
# senza shell non troverebbe per nome nudo.
_BIN = os.environ.get("CK_AB_CLAUDE", "claude")
CLAUDE_BIN = shutil.which(_BIN) or _BIN
MODEL = os.environ.get("CK_AB_MODEL", "")
TIMEOUT_S = int(os.environ.get("CK_AB_TIMEOUT", "180"))
MAX_ATTEMPTS = 3

VERDICT_OK = "VERDETTO: INVARIANTE"
VERDICT_BAD = "VERDETTO: DEGRADATO"

PROMPT = """\
Sei un giudice di answer-invariance (T4 della pipeline context-kernel).
Sotto trovi l'ORIGINALE di un output di tool ({tool}) e la versione COMPRESSA
che e' entrata al suo posto nel contesto di un agente di coding.

Giudica UNA cosa sola: la compressa conserva tutti i segnali su cui l'agente
potrebbe dover agire? (errori, warning, esiti di test, path, versioni,
conteggi, nomi di simboli). I marcatori [context-kernel: ...] e [x N] sono
attesi e legittimi: non sono perdita di segnale. La perdita di righe di puro
rumore (progress, log ripetitivi, corpo di codice riassunto in firme) e'
il comportamento voluto: e' DEGRADATO solo se manca un segnale AZIONABILE.

Rispondi in massimo 6 righe. L'ULTIMA riga deve essere esattamente:
VERDETTO: INVARIANTE
oppure:
VERDETTO: DEGRADATO — <i segnali persi, brevi>

=== ORIGINALE ===
{original}

=== COMPRESSA ===
{compressed}
"""


def _load() -> dict:
    try:
        with open(AB_STATE, encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict):
            st.setdefault("counter", 0)
            st.setdefault("pending", [])
            st.setdefault("ok", 0)
            st.setdefault("degraded", 0)
            st.setdefault("last_run", None)
            return st
    except Exception:                          # noqa: BLE001
        pass
    return {"counter": 0, "pending": [], "ok": 0, "degraded": 0,
            "last_run": None}


def _save(st: dict) -> None:
    tmp = f"{AB_STATE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, AB_STATE)


def _unpack(z: str) -> str:
    try:
        return zlib.decompress(base64.b64decode(z)).decode("utf-8", "replace")
    except Exception:                          # noqa: BLE001
        return ""


def _sample_label(s: dict) -> str:
    where = s.get("file") or "-"
    ts = s.get("ts")
    when = (datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
            if ts else "?")
    return f"{s.get('tool', '?')} {where} ({when}, sessione {s.get('session', '?')})"


def _judge(prompt: str) -> str | None:
    """Una chiamata headless al giudice. None = chiamata fallita."""
    cmd = [CLAUDE_BIN, "-p"]
    if MODEL:
        cmd += ["--model", MODEL]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              text=True, timeout=TIMEOUT_S)
    except FileNotFoundError:
        print(f"Giudice non trovato: `{CLAUDE_BIN}`. Imposta CK_AB_CLAUDE "
              "o installa Claude Code.", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"Giudizio scaduto dopo {TIMEOUT_S}s.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().split("\n")[-1:]
        print(f"Giudice uscito con {proc.returncode}: {' '.join(err)}",
              file=sys.stderr)
        return None
    return proc.stdout


def _parse_verdict(answer: str) -> tuple[str, str] | None:
    """('ok'|'degraded', dettaglio) — None se il verdetto non c'e'."""
    for line in reversed(answer.strip().split("\n")):
        line = line.strip()
        if line.startswith(VERDICT_OK):
            return "ok", ""
        if line.startswith(VERDICT_BAD):
            detail = line[len(VERDICT_BAD):].strip(" —-–:")
            return "degraded", detail
    return None


def print_cron() -> int:
    """Stampa una riga crontab pronta da incollare: giudizio quotidiano dei
    campioni in attesa. NON tocca il crontab dell'utente: il giudice manda
    CONTENUTI a un modello (README §11), l'installazione deve essere una
    scelta esplicita."""
    me = os.path.abspath(__file__)
    claude = shutil.which(CLAUDE_BIN) or CLAUDE_BIN
    line = (f'30 9 * * * CK_AB_CLAUDE="{claude}"'
            + (f' CK_AB_MODEL="{MODEL}"' if MODEL else "")
            + f' "{sys.executable}" "{me}" --limit 5'
            f' >> "$HOME/.context-kernel-ab-cron.log" 2>&1')
    print("Riga per `crontab -e` (giudizio A/B quotidiano alle 09:30, "
          "max 5 campioni, log in ~/.context-kernel-ab-cron.log):\n")
    print(line)
    print("\nRicorda: ab_verify.py e' l'unico comando del plugin che MANDA "
          "contenuti a un modello (README §11). Installa il cron solo se "
          "questo ti sta bene; in alternativa il brief di SessionStart "
          "ricorda i campioni in attesa a ogni nuova sessione.")
    return 0


def status(st: dict) -> str:
    pend = len(st.get("pending", []))
    return (f"A/B invariance: {st.get('ok', 0)} invarianti, "
            f"{st.get('degraded', 0)} degradate, {pend} campioni in attesa "
            f"(campionate {st.get('counter', 0)} elisioni)")


def main() -> int:
    argv = sys.argv[1:]
    if "--cron" in argv:
        return print_cron()
    dry = "--dry-run" in argv
    limit = None
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit vuole un intero.", file=sys.stderr)
            return 2

    st = _load()
    if "--status" in argv:
        print(status(st))
        return 0
    if not st["pending"]:
        print(f"Nessun campione in attesa. {status(st)}")
        return 0

    todo = st["pending"] if limit is None else st["pending"][:limit]
    print(f"{len(todo)} campioni da giudicare (giudice: {CLAUDE_BIN}"
          f"{' --model ' + MODEL if MODEL else ''})\n")

    judged_any = False
    still: list[dict] = []
    for s in st["pending"]:
        if s not in todo:
            still.append(s)
            continue
        original = _unpack(s.get("orig_z", ""))
        compressed = _unpack(s.get("comp_z", ""))
        if not original or not compressed:
            print(f"  scartato (campione illeggibile): {_sample_label(s)}")
            continue
        prompt = PROMPT.format(tool=s.get("tool", "?"),
                               original=original, compressed=compressed)
        if dry:
            print(f"--- prompt per {_sample_label(s)} ---")
            print(prompt)
            still.append(s)
            continue
        answer = _judge(prompt)
        verdict = _parse_verdict(answer) if answer else None
        if verdict is None:
            s["attempts"] = s.get("attempts", 0) + 1
            if s["attempts"] >= MAX_ATTEMPTS:
                print(f"  scartato dopo {MAX_ATTEMPTS} tentativi: "
                      f"{_sample_label(s)}")
            else:
                still.append(s)
                print(f"  rimandato (risposta non parsabile, tentativo "
                      f"{s['attempts']}): {_sample_label(s)}")
            continue
        judged_any = True
        kind, detail = verdict
        iso = datetime.datetime.now().isoformat(timespec="seconds")
        if kind == "ok":
            st["ok"] = st.get("ok", 0) + 1
            print(f"  ✓ INVARIANTE  {_sample_label(s)}")
        else:
            st["degraded"] = st.get("degraded", 0) + 1
            st["degradations"] = (st.get("degradations", []) + [{
                "ts": iso, "tool": s.get("tool"), "file": s.get("file"),
                "session": s.get("session"), "missing": detail,
            }])[-20:]
            print(f"  ⚠ DEGRADATO   {_sample_label(s)}")
            if detail:
                print(f"                persi: {detail}")
        st["last_run"] = iso

    st["pending"] = still
    if not dry:
        _save(st)
        print(f"\n{status(st)}")
        if judged_any and st.get("degraded"):
            print("Le degradazioni (ultime 20) sono in "
                  f"{AB_STATE} -> 'degradations': usale per tarare "
                  "le euristiche di compress.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
