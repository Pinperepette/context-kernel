---
description: Giudica i campioni A/B di answer-invariance in coda (contesto pieno vs proiettato). Opzioni: status, dry-run, limit N.
argument-hint: "[status] | [dry-run] | [limit N]"
allowed-tools: Bash
---

# context-kernel — verify (A/B answer-invariance)

Argomenti: `$ARGUMENTS`

- **Nessun argomento** → giudica i campioni pendenti sul traffico reale:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/ab_verify.py"
  ```
- **`status`** → mostra solo quanti campioni sono in coda, senza giudicarli:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/ab_verify.py" --status
  ```
- **`dry-run`** → stampa i prompt che verrebbero valutati, senza chiamare il giudice:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/ab_verify.py" --dry-run
  ```
- **`limit N`** → giudica al massimo N campioni:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/ab_verify.py" --limit N
  ```

Riporta l'esito in sintesi: quanti giudicati, quanti A(x)=A(π(x)) confermati, quante divergenze (queste ultime vanno investigate — sono il segnale che una proiezione ha perso risposta).
