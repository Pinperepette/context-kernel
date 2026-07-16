---
name: kernel-pipeline
description: "Orchestrazione completa della pipeline kernel su un bug: T1 compressione (hook, ambientale) -> T2 repo slice -> T3 carta del task -> fix -> T4 verifica. Usala per bug non banali in repo medio-grandi; per bug piccoli usa direttamente kernel-repo-slice o niente."
---

# kernel-pipeline — C' = T4(T3(T2(T1(C))))

Ogni stadio e' un operatore con un invariante dichiarato. T1 (compressione
degli output dei tool) e' ambientale: gli hook la applicano gia'. Questa
skill orchestra il resto.

## Quando

Bug non banale in repo con molti file. Se il repo e' piccolo o il fix e'
ovvio, salta la pipeline: il costo degli stadi deve valere meno del vagare.

## Stadi

1. **T2 — slice del repo** (deterministico): segui `kernel-repo-slice` col
   sintomo. Ottieni il manifest C2. In Pi puoi delegare al tool isolato
   `kernel_scout`; in Claude Code all'agent `kernel-scout`.
2. **T3 — carta del task** (semantico, citabile): segui `kernel-invariants`
   sui file di C2. Ottieni la carta C3. In Pi puoi delegare al tool isolato
   `kernel_extractor`; in Claude Code all'agent `kernel-extractor`.
3. **Fix**: lavora SOLO da C3 + i file citati. Regola page-fault: se serve
   un file fuori slice, leggilo e ANNOTA il miss (file + perche' serviva).
4. **T4 — verifica**: ripassa la carta vincolo per vincolo contro il diff.
   A campione (fix delicati): `kernel-verify` con Q = il bug, x = i file
   citati interi, pi(x) = la carta — la risposta cambia? In Pi puoi delegare
   al tool isolato `kernel_verifier`; in Claude Code all'agent
   `kernel-verifier`.

## Telemetria (per la curva rate-distortion)

A fine giro annota quattro numeri nel report:
- rate: file in slice / file scansionati (dal manifest)
- fault: quanti page fault (file fuori slice letti davvero)
- repair: costo dei fault (righe lette fuori slice)
- verdetto T4: vincoli rispettati / violati

Un fault alto con repair basso = la slice era aggressiva ma il modello
regge (bene). Vincoli violati non citati = T3 ha perso segnale (male:
stringere T3, non allargare T2).

### Persistenza (OBBLIGATORIA a fine giro)
Oltre al report, appendi UNA riga JSON per run a `~/.context-kernel-pipeline.jsonl`
(e' il dataset della curva rate-distortion). Schema — coi numeri veri del run:

```bash
python3 - <<'PYEOF'
import json, os, datetime
rec = {
    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    "repo": "/path/del/repo", "scanned": 1415, "slice": 123,
    "fault": 2, "repair_righe": 15,
    "verdetto": "PASS", "vincoli": "12/12",
    "note": "cosa ha morso il fault, se c'e' stato",
}
rec["rate"] = round(1 - rec["slice"] / rec["scanned"], 3)
with open(os.path.expanduser("~/.context-kernel-pipeline.jsonl"), "a") as f:
    f.write(json.dumps(rec) + "\n")
PYEOF
```
