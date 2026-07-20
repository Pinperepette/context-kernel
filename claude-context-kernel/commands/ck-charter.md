---
description: Carta del task attiva (T3) — mostra i vincoli citati, ri-risolve le citazioni driftate, o azzera la carta.
argument-hint: "[get] | [refresh] | [clear]"
allowed-tools: Bash
---

# context-kernel — charter (carta del task)

Argomenti: `$ARGUMENTS`

La carta è l'insieme dei vincoli che il fix deve rispettare, ognuno con citazione `file:riga`. Quando è salvata diventa **attiva**: una guardia PreToolUse inietta i vincoli rilevanti prima di ogni Edit/Write/Bash sui file citati, e sopravvive all'auto-compact.

- **`get`** (default) → mostra la carta attiva:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/charter.py" get
  ```
- **`refresh`** → ri-risolve deterministicamente i `file:riga` driftati contro l'anchor catturato al save. Match unico → aggiorna; zero o ambiguo → dichiarato irrisolvibile, mai indovinato:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/charter.py" refresh
  ```
- **`clear`** → azzera la carta (usalo quando il task è cambiato):
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/charter.py" clear
  ```

Se non c'è carta attiva, dillo in una riga e suggerisci che la carta si genera dalla pipeline kernel (skill `kernel-invariants` / `kernel-pipeline`).
