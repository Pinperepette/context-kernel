---
description: Stato del context-kernel in un colpo d'occhio — risparmio token, canary, coda A/B, carta del task attiva.
allowed-tools: Bash
---

# context-kernel — status

Presenta all'utente lo stato del plugin in poche righe. Esegui i comandi e sintetizza, non incollare output grezzi lunghi.

1. **Risparmio + canary + ledger A/B** (report completo):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/savings.py"
   ```
   Estraine: compressioni totali, token risparmiati (e %), costo input evitato, stato canary (verde/violazioni), voci A/B pendenti.

2. **Coda A/B da giudicare**:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/ab_verify.py" --status
   ```

3. **Carta del task attiva** (se presente):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/charter.py" get
   ```

Riassumi in un blocco compatto: `risparmio`, `canary`, `A/B pendenti`, `carta attiva sì/no`. Se qualcosa richiede azione (canary rosso, campioni A/B in coda, citazioni driftate) chiudilo con una riga `→ prossima azione: /ck-verify` o simile.
