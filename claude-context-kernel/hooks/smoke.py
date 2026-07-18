#!/usr/bin/env python3
"""
smoke.py — il rito di verifica LIVE, scriptato (1.17.0).

Il dato empirico che questo file istituzionalizza: OGNI verifica dal vivo
delle release ha trovato bug che 300+ test non vedevano (additionalContext
ignorato, canary contro parcheggio, fixture nello store reale, ...) —
perche' i test esercitano gli operatori, il rito esercita il CONTRATTO con
l'harness reale. Da qui: una release non e' "verde" finche' lo smoke non
passa in una sessione vera.

Protocollo a DUE comandi, da eseguire in una sessione Claude Code viva
su questo repo (Bash normale, senza `# ck:raw` sul generate):

    python3 hooks/smoke.py generate    # 400 righe con AGO CALCOLATO a
                                       # runtime (mai nel comando, mai nel
                                       # contesto) — il hook la comprime
    python3 hooks/smoke.py check       # verifica sul TRANSCRIPT REALE
                                       # cio' che l'harness ha DAVVERO fatto

Cosa asserisce `check` (PASS/FAIL per punto, exit != 0 su ogni FAIL):
  1. il tool_result del generate sta nel transcript della sessione;
  2. e' la versione COMPRESSA (footer presente: updatedToolOutput onorato);
  3. l'ago e' stato ELISO dal contesto;
  4. il footer dichiara il parcheggio e la chiave;
  5. la chiave esiste nello store del parcheggio;
  6. recall.py KEY --grep ritrova l'ago, numerato (page fault inverso);
  7. il canary non ha accumulato NUOVI failed dal generate (niente falsi
     allarmi sul contratto);
  8. advisor in 4 punti sul context state REALE della sessione (avviso a
     soglia bassa; one-shot; subagent muto; soglia alta muta) — SKIP
     dichiarato se il tap della sessione non e' ancora stato scritto.

Copertura DICHIARATA: la gamba effimera e' il Bash (rappresentativo:
stessa via di parcheggio di WebFetch/MCP); compact reale, resume e guardie
restano al rito manuale (richiedono eventi harness non scriptabili da qui).

Stato tra i due comandi: CK_SMOKE_STATE (default ~/.context-kernel-smoke
.json) — id univoco del lotto, ago, snapshot canary. Zero rete, zero API.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time

try:
    import _utf8  # noqa: F401 — import con effetto: stream UTF-8 (Windows)
except ImportError:                        # embed per-path: stream dell'host
    pass

HOOKS = os.path.dirname(os.path.abspath(__file__))
SMOKE_STATE = os.path.expanduser(
    os.environ.get("CK_SMOKE_STATE", "~/.context-kernel-smoke.json"))
PARK_STATE = os.path.expanduser(
    os.environ.get("CK_PARK_STATE", "~/.context-kernel-park.json"))
CANARY_STATE = os.path.expanduser(
    os.environ.get("CK_CANARY_STATE", "~/.context-kernel-canary.json"))
CONTEXT_STATE = os.path.expanduser(
    os.environ.get("CK_CONTEXT_STATE", "~/.context-kernel-context.json"))
TRANSCRIPTS = os.path.expanduser(
    os.environ.get("CK_SMOKE_TRANSCRIPTS", "~/.claude/projects"))
RECENT_S = 2 * 3600                        # transcript piu' vecchi: fuori
N_LINES = 400
NEEDLE_AT = 237                            # 1-based, in mezzo al rumore


def _canary_failed() -> int:
    try:
        with open(CANARY_STATE, encoding="utf-8") as f:
            return int((json.load(f) or {}).get("failed", 0))
    except Exception:                      # noqa: BLE001
        return 0


def generate() -> int:
    """Emette il lotto sintetico con l'ago calcolato e salva lo stato."""
    seed = f"{time.time_ns()}-{os.getpid()}"
    digest = hashlib.sha1(seed.encode()).hexdigest()
    run_id = digest[:8]
    # ago DECIMALE (niente hex: non deve somigliare a hash/segnale) e
    # formulazione senza parole di segnale (error/warn/fail/path)
    needle = f"sentinella-{int(digest, 16) % 100_000:05d}"
    state = {"ts": time.time(), "id": run_id, "needle": needle,
             "canary_failed": _canary_failed()}
    tmp = f"{SMOKE_STATE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, SMOKE_STATE)
    print(f"smoke context-kernel — lotto {run_id} — inizio")
    for i in range(2, N_LINES):
        if i == NEEDLE_AT:
            print(f"riga {i:03d} — {needle} registrata nel lotto notturno")
        else:
            print(f"riga {i:03d} — elaborazione lotto completata senza variazioni")
    print(f"smoke context-kernel — lotto {run_id} — fine")
    return 0


def _result_text(obj: dict) -> str | None:
    """Testo del tool_result in una riga di transcript gia' parsata."""
    for c in (obj.get("message") or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "tool_result":
            cc = c.get("content")
            if isinstance(cc, str):
                return cc
            if isinstance(cc, list):
                return "\n".join(b.get("text", "") for b in cc
                                 if isinstance(b, dict)
                                 and b.get("type") == "text")
    return None


def _find_result(run_id: str) -> tuple[str, str] | None:
    """(transcript_path, testo del tool_result del generate) — cerca il
    lotto per id nei transcript recenti, dal piu' fresco."""
    marker = f"lotto {run_id}"
    cands = []
    for base, _dirs, files in os.walk(TRANSCRIPTS):
        for fn in files:
            if fn.endswith(".jsonl"):
                p = os.path.join(base, fn)
                try:
                    if time.time() - os.path.getmtime(p) < RECENT_S:
                        cands.append(p)
                except OSError:
                    pass
    for p in sorted(cands, key=os.path.getmtime, reverse=True):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if marker not in line or "tool_result" not in line:
                        continue
                    try:
                        text = _result_text(json.loads(line))
                    except Exception:      # noqa: BLE001
                        continue
                    if text and marker in text:
                        return p, text
        except OSError:
            continue
    return None


def _advisor_checks(transcript: str) -> tuple[str, list[str]]:
    """('PASS'|'SKIP'|'FAIL', dettagli) — advisor sul context state reale."""
    sid = os.path.basename(transcript)[:-6][:8]
    try:
        with open(CONTEXT_STATE, encoding="utf-8") as f:
            rec = (json.load(f) or {}).get(sid) or {}
        if int(rec.get("context_tokens") or 0) <= 0:
            return "SKIP", ["tap della sessione non ancora scritto"]
    except Exception:                      # noqa: BLE001
        return "SKIP", ["context state assente"]
    adv = os.path.join(HOOKS, "compact_advisor.py")
    iso = f"{SMOKE_STATE}.advise.{os.getpid()}"
    payload = json.dumps({"tool_name": "Bash", "transcript_path": transcript})

    def run(threshold: str, pl: str = payload, state: str | None = None) -> str:
        env = {**os.environ, "CK_COMPACT_ADVISE": threshold,
               "CK_ADVISE_STATE": state or iso}
        try:
            return subprocess.run(
                [sys.executable, adv], input=pl, capture_output=True,
                text=True, env=env, timeout=30).stdout.strip()
        except Exception:                  # noqa: BLE001
            return "<errore subprocess>"

    details, ok = [], True
    first = run("0.05")
    if "additionalContext" in first and "/compact" in first:
        details.append("avviso a soglia bassa: PASS")
    else:
        details.append(f"avviso a soglia bassa: FAIL ({first[:80]})")
        ok = False
    if run("0.05") == "{}":
        details.append("one-shot per sessione: PASS")
    else:
        details.append("one-shot per sessione: FAIL")
        ok = False
    sub = json.dumps({"tool_name": "Bash", "transcript_path": transcript,
                      "agent_id": "smoke-sub"})
    if run("0.05", pl=sub, state=iso + ".b") == "{}":
        details.append("subagent muto: PASS")
    else:
        details.append("subagent muto: FAIL")
        ok = False
    if run("0.99", state=iso + ".c") == "{}":
        details.append("soglia alta muta: PASS")
    else:
        details.append("soglia alta muta: FAIL")
        ok = False
    for suffix in ("", ".b", ".c"):
        try:
            os.unlink(iso + suffix)
        except OSError:
            pass
    return ("PASS" if ok else "FAIL"), details


def check() -> int:
    try:
        with open(SMOKE_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                      # noqa: BLE001
        print("FAIL  stato smoke assente: eseguire prima `smoke.py generate`")
        return 1
    run_id, needle = st["id"], st["needle"]
    results: list[tuple[str, str]] = []

    found = _find_result(run_id)
    if not found:
        print(f"FAIL  lotto {run_id} non trovato in nessun transcript "
              f"recente sotto {TRANSCRIPTS} — sessione diversa, o il "
              "risultato non e' (ancora) stato scritto")
        return 1
    transcript, text = found
    results.append(("PASS", f"lotto {run_id} trovato nel transcript "
                    f"{os.path.basename(transcript)}"))

    if "[context-kernel:" in text and "token, -" in text:
        results.append(("PASS", "tool_result COMPRESSO nel transcript "
                        "(updatedToolOutput onorato dall'harness)"))
    else:
        results.append(("FAIL", "tool_result INTEGRALE nel transcript: "
                        "l'harness ha ignorato updatedToolOutput"))
    if needle not in text:
        results.append(("PASS", "ago eliso dal contesto"))
    else:
        results.append(("FAIL", "ago ancora presente: nessuna elisione "
                        "(soglie? plugin disattivo?)"))

    m = re.search(r"parcheggiato: python3 .*recall\.py\"? ([0-9a-f]{10})", text)
    key = m.group(1) if m else None
    if key:
        results.append(("PASS", f"footer dichiara il parcheggio (chiave {key})"))
        try:
            with open(PARK_STATE, encoding="utf-8") as f:
                in_store = key in (json.load(f) or {})
        except Exception:                  # noqa: BLE001
            in_store = False
        results.append(("PASS", "chiave presente nello store") if in_store
                       else ("FAIL", "chiave assente dallo store del parcheggio"))
        rec = subprocess.run(
            [sys.executable, os.path.join(HOOKS, "recall.py"),
             key, "--grep", "sentinella"],
            capture_output=True, text=True, timeout=30)
        if needle in rec.stdout and str(NEEDLE_AT) in rec.stdout:
            results.append(("PASS", "recall --grep ritrova l'ago, numerato "
                            "(page fault inverso funzionante)"))
        else:
            results.append(("FAIL", "recall non ritrova l'ago "
                            f"({rec.stdout[:80]!r})"))
    else:
        results.append(("FAIL", "footer senza hint di parcheggio"))

    failed_now = _canary_failed()
    if failed_now <= st.get("canary_failed", 0):
        results.append(("PASS", "canary: nessun nuovo failed dal generate"))
    else:
        results.append(("FAIL", f"canary: failed {st.get('canary_failed', 0)}"
                        f" -> {failed_now} — indagare PRIMA di fidarsi del ledger"))

    verdict, details = _advisor_checks(transcript)
    results.append((verdict, "advisor (4 punti): " + "; ".join(details)))

    bad = 0
    for v, msg in results:
        print(f"{v:5s} {msg}")
        bad += int(v == "FAIL")
    print(f"\nsmoke: {len(results) - bad}/{len(results)} punti superati"
          + ("" if not bad else f", {bad} FALLITI"))
    return 1 if bad else 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "generate":
        return generate()
    if cmd == "check":
        return check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
