---
description: Report del risparmio token del context-kernel. Passa "html" per il report autoconsistente, "reset-canary" per acquietare i fault investigati.
argument-hint: "[html [path]] | [reset-canary]"
allowed-tools: Bash
---

# context-kernel — savings

Argomenti: `$ARGUMENTS`

- **Nessun argomento** → report testuale completo:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/savings.py"
  ```
- **`html [path]`** → report HTML autoconsistente (light+dark, zero asset esterni). Se l'utente indica un path usalo, altrimenti default dello script; a fine comando mostra il path del file scritto:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/savings.py" --html [path]
  ```
- **`reset-canary`** → acquieta i fault del canary dopo averli investigati:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/savings.py" --reset-canary
  ```

Mostra l'output del report. Per il caso HTML, conferma solo il path scritto senza incollare l'HTML.
