---
name: kernel-repo-slice
description: "T2 della pipeline kernel: proietta un intero repository sul working set rilevante per un bug (P_Q a livello repo). Usalo PRIMA di esplorare un repo grande quando hai un sintomo concreto: stack trace, messaggio d'errore, file indiziati. Output: manifest ordinato con motivazioni + esclusioni recuperabili (page fault)."
---

# kernel-repo-slice — working set del repo indotto dal bug

Dato un task Q (il bug), calcola C' = P_Q(C): la proiezione del repository
sul sottinsieme di file che puo' influenzare il sintomo.

## Quando usarla

- Bug con stack trace / messaggio d'errore in un repo medio-grande.
- PRIMA di grep esplorativi a tappeto: la slice guida l'esplorazione.
- NON serve su repo piccoli (< ~50 file): leggi e basta.

## Procedura

1. Raccogli il sintomo piu' concreto disponibile: stack trace intero >
   messaggio d'errore quotato > path indiziati > descrizione vaga.
2. Esegui lo slicer deterministico:

- **Pi:** chiama il tool nativo `kernel_repo_slice`; se `budget` manca viene
  derivato dalla finestra di contesto viva.
- **Claude Code:**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/kernel-repo-slice/scripts/repo_slice.py <repo_root> \
    --symptom "$(cat /percorso/sintomo.txt)"        # o --symptom "testo"
# opzioni: --seed <file> (aggiunge seed espliciti), --importers-depth N,
#          --max-files N, --json
```

Negli altri harness risolvi `scripts/repo_slice.py` relativamente alla directory
di questa skill.

3. Leggi il manifest: seed (con provenienza), file per rilevanza
   (dipendenza/importatore/test + hop), conteggio esclusi.
4. Lavora DALLA slice: leggi prima i seed, poi le dipendenze a 1 hop,
   i test correlati sono il riproduttore.

## Budget (operatore costo)
La risorsa vera e' la FINESTRA DI CONTESTO: `--budget N` e' in TOKEN stimati
(size/4) che il working set costera' quando i file verranno letti — 10 file
enormi costano piu' di 100 piccoli. Lo script sceglie DA SOLO la chiusura
piu' ricca che rientra nel vincolo (scala misurata col bench di sufficienza:
regge a ogni gradino). Ordini di grandezza: 30k token ~ working set generoso,
10k ~ stretto. Se nemmeno il minimo (seed + test correlati) rientra, scende
DA SOLO a granularita' di SIMBOLO (T2b): dai frame del traceback ricava il
simbolo top-level che racchiude ogni riga — e se e' un metodo di classe,
solo le righe del metodo — e il manifest guadagna la sezione `## T2b` con
etichette, costo e COMANDI DI ESTRAZIONE pronti (sed per i metodi,
slice.py per le funzioni top-level). Leggi le slice coi comandi, non i file
interi; page fault = risali al file solo se la slice non basta. Misurato su
pandas: minimo file-level ~372k token -> T2b ~15k (-96%). Il manifest
riporta config scelta e costo nella riga `budget:`. Controllo manuale:
`--deps-depth` e `--importers-depth`.

## Regola del page fault (importante)

L'esclusione e' un **prior, non un divieto**. Il grafo degli import non vede
dynamic import, dependency injection, config file, alias di bundler. Se
l'evidenza punta fuori dalla slice (nome citato in un errore, config
sospetta), **leggi il file fuori slice senza esitare**: un miss costa un
Read, non una risposta sbagliata.

## Fail-safe

Se lo script non riconosce alcun seed lo dice esplicitamente e non proietta
nulla: in quel caso NON fingere una slice — o trovi un sintomo migliore
(riproduci il bug, prendi lo stack trace) o esplori normalmente.
