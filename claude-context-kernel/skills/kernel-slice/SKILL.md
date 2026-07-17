---
name: kernel-slice
description: Estrae la fetta minimale di un file Python rilevante per un simbolo (funzione/classe), scartando tutto cio' che non puo' influenzarne il comportamento. Usalo prima di leggere per intero un file grande quando ti interessa solo un simbolo specifico.
disable-model-invocation: false
effort: low
---

# kernel-slice — proiezione formale del codice

Quando serve ragionare su **un simbolo specifico** (una funzione, una classe)
dentro un file Python grande, non leggere l'intero file: estrai solo la sua
chiusura di raggiungibilita' sul grafo def-use. Tutto il resto (funzioni morte,
import inutilizzati, classi scollegate) non puo' cambiare il comportamento del
target, quindi e' rumore per il contesto.

## Come usarlo

- **Pi:** chiama il tool nativo `kernel_slice` con `file` e `symbols`.
- **Claude Code:** esegui via Bash lo script incluso:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kernel-slice/scripts/slice.py" <file.py> <simbolo> [<simbolo2> ...]
```

Negli altri harness risolvi `scripts/slice.py` relativamente alla directory
di questa skill. Lo script stampa **solo** le definizioni top-level raggiungibili
dai target, piu' gli import effettivamente usati. Ragiona su quell'output invece
del file intero.

## Garanzia

E' answer-preserving *per costruzione* rispetto ai simboli chiesti: il
comportamento di un simbolo dipende solo dalle sue dipendenze transitive.
Se un simbolo non e' riconosciuto, o il file non e' `.py`, lo script ritorna
il file intero (fail-safe): non perde mai informazione rilevante.

## Quando NON usarlo

- Se ti serve una visione d'insieme del file (non un simbolo specifico).
- Se il file e' piccolo (< ~100 righe): leggerlo intero costa poco.
