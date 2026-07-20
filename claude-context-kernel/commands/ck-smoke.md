---
description: Smoke test end-to-end della compressione su un transcript reale — genera un ago e verifica che sopravviva alla proiezione.
argument-hint: "generate | check"
allowed-tools: Bash
---

# context-kernel — smoke test

Argomenti: `$ARGUMENTS`

Protocollo deterministico in due comandi, read-only sugli stati del plugin (scrive solo il proprio stato isolato, che poi cancella).

- **`generate`** → emette ~400 righe con un ago calcolato al momento:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/smoke.py" generate
  ```
- **`check`** → verifica, sul transcript reale, che l'ago sia sopravvissuto alla compressione:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/smoke.py" check
  ```

Il flusso tipico: lancia `generate`, lascia che la riga passi nel contesto, poi `check`. Riporta PASS/FAIL e, se FAIL, quale segnale è andato perso.
