---
description: Rilevanza rivelata dal transcript (T5) e attuazione ESPLICITA dei tassi/prior appresi. Default: solo report. Mai tuning silenzioso.
argument-hint: "[report] | [apply-rates] | [write-priors] | [--last N] [--json]"
allowed-tools: Bash
---

# context-kernel — tune (rilevanza rivelata, T5 → T1)

Argomenti: `$ARGUMENTS`

Chiude il ciclo T5→T1: dai transcript reali misura cosa è stato davvero riletto
(page fault ricorrenti) e, **solo su comando esplicito**, ne scrive i tassi/prior.
Per contratto non c'è mai tuning silenzioso, e le attuazioni scattano solo su
**ricorrenza ≥ 2** sessioni/occorrenze, mai sul singolo episodio.

- **`report`** (default) → aggrega la rilevanza rivelata senza scrivere nulla:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/revealed.py" --aggregate
  ```
- **`apply-rates`** → scrive i tassi per-estensione appresi dai fault ricorrenti.
  **Relax-only**: possono solo ALLEGGERIRE la compressione (`relax`/`raw`) per una
  categoria che è costata riletture, mai stringerla:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/revealed.py" --aggregate --apply-rates
  ```
- **`write-priors`** → scrive i prior di slice (seed additivi/flag freddi). **Add-only**:
  aggiungono seed o flaggano freddi, mai escludono:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/revealed.py" --aggregate --write-priors
  ```

Modificatori: `--last N` (quanti transcript considerare), `--json` (output macchina).
Dopo un'attuazione, riporta cosa è stato scritto (la sezione `## attuazione esplicita`).
