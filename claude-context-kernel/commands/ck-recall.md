---
description: Recupera un output parcheggiato dalla sessione (l'inverso della proiezione). Cerca fra tutti i parcheggi o pagina una chiave dal footer.
argument-hint: "search REGEX | <chiave> [--grep P | --lines A-B] | list"
allowed-tools: Bash
---

# context-kernel — recall (recall storage di sessione)

Argomenti: `$ARGUMENTS`

Un output di Bash/MCP/WebFetch eliso non si recupera rileggendo un file: il comando è già passato. Al momento dell'elisione l'originale è parcheggiato su disco. Questo comando è l'accesso mirato a quel parcheggio.

- **`search REGEX`** → grep su TUTTI gli output parcheggiati della sessione, poi indica quale chiave ha corrisposto:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/recall.py" --search REGEX
  ```
- **`<chiave>`** (dal footer `[parcheggiato: ...]`) con recupero mirato:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/recall.py" <chiave> --grep PATTERN
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/recall.py" <chiave> --lines A-B
  ```
- **`list`** → elenca le chiavi parcheggiate:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/recall.py" --list
  ```

Restituisci solo le righe richieste, deterministicamente — nessun ranking, nessun modello.
