---
description: Health check dell'installazione context-kernel — Python, hook registrati, script presenti, MCP, statusline, canary, coda A/B.
allowed-tools: Bash
---

# context-kernel — doctor

Esegui il preflight deterministico e mostra il referto a righe `[ok]/[warn]/[ko]`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/doctor.py"
```

Controlla: Python ≥ 3.8, hook registrati (hooks.json cita compress.py), script core presenti, MCP server, superficie comandi `/ck-*`, stato canary, coda A/B. Exit 1 se ci sono bloccanti (`[ko]`), 0 altrimenti.

Mostra l'output e, se ci sono `[warn]`, chiudi con la prossima azione consigliata (es. `/ck-verify` per la coda A/B, `/ck-savings reset-canary` per il canary).
