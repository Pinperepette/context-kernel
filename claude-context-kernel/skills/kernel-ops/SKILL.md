---
name: kernel-ops
description: Operazioni e diagnostica del plugin context-kernel a linguaggio naturale, senza dover digitare slash command. Usala quando l'utente chiede — con parole sue — lo stato o la salute del kernel, quanti token ha risparmiato, un health-check (doctor), di giudicare i campioni A/B (answer-invariance), di recuperare un output parcheggiato/eliso (recall), la carta del task attiva, uno smoke test della compressione, o i tassi/prior appresi (tune). Esempi: "come va il context-kernel", "quanto ho risparmiato", "fai il doctor del kernel", "controlla che il plugin sia a posto", "giudica gli A/B", "recupera quell'output parcheggiato", "che carta del task ho attiva". Instrada verso lo script giusto; le attuazioni che SCRIVONO stato restano sempre esplicite.
disable-model-invocation: false
effort: low
---

# kernel-ops — la superficie operativa del context-kernel a parole

Questa skill è il gemello a linguaggio naturale dei comandi `/ck-*`: stessa
funzione, stessi script, ma raggiungibile dicendo cosa vuoi invece di ricordare
la sintassi. Gli script vivono sotto `${CLAUDE_PLUGIN_ROOT}/hooks/` (con la via
plugin) oppure, per l'install manuale, nella cartella `hooks/` del plugin —
risolvi il path una volta e riusalo.

## Principio (non tradire la filosofia)

Il plugin non fa **mai tuning silenzioso**. Questa skill può leggere e
diagnosticare liberamente, ma tutto ciò che **scrive stato** va fatto solo su
richiesta esplicita dell'utente, annunciando cosa sta per cambiare:
`apply-rates` (relax-only), `write-priors` (add-only), `charter clear`,
`savings reset-canary`. Nel dubbio: mostra, non attuare.

## Instradamento dell'intento

Capisci cosa chiede l'utente e lancia il comando corrispondente (poi sintetizza
l'output, non incollare referti lunghi):

| L'utente vuole… | Comando |
| --- | --- |
| stato/colpo d'occhio (risparmio, canary, coda A/B, carta) | `savings.py` + `ab_verify.py --status` + `charter.py get` |
| salute dell'installazione (health-check) | `doctor.py` |
| report risparmio token | `savings.py` (`--html [path]` per la pagina) |
| **acquietare** il canary dopo indagine (esplicito) | `savings.py --reset-canary` |
| giudicare i campioni A/B | `ab_verify.py` (`--status`, `--dry-run`, `--limit N`) |
| recuperare un output parcheggiato | `recall.py --search REGEX` \| `recall.py <chiave> --grep/--lines` |
| vedere/rinfrescare/azzerare la carta del task | `charter.py get \| refresh \| clear` |
| smoke test della compressione | `smoke.py generate` poi `smoke.py check` |
| rilevanza rivelata (T5), solo report | `revealed.py --aggregate` |
| **attuare** tassi/prior appresi (esplicito) | `revealed.py --aggregate --apply-rates` \| `--write-priors` |

Tutti eseguibili con `python3 <hooks>/<script>`. Se l'utente preferisce la forma
digitata, gli stessi passi sono i comandi `/ck-status`, `/ck-doctor`,
`/ck-savings`, `/ck-verify`, `/ck-recall`, `/ck-charter`, `/ck-smoke`, `/ck-tune`.
