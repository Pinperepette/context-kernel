---
name: kernel-invariants
description: "T3 della pipeline kernel: dall'output dello slicer estrae la CARTA DEL TASK — i vincoli che il fix deve rispettare, ognuno con citazione file:riga. Converte massa di codice in proposizioni verificabili. Usala dopo kernel-repo-slice e prima di scrivere il fix."
---

# kernel-invariants — estrazione dei vincoli (T3)

Input: il manifest di kernel-repo-slice (o una lista di file) + il task Q.
Output: la **carta del task** — poche proposizioni citabili che il fix deve
rispettare. E' lossy per scelta: converte codice in vincoli. La regola che
rende l'operazione verificabile: **ogni vincolo cita la riga da cui viene**.

## Procedura

1. Leggi i file della slice nell'ordine del manifest (seed -> 1 hop -> test).
   Per file grandi Python, usa `kernel_slice` (MCP) sul simbolo rilevante
   invece di leggere tutto.
2. Estrai SOLO cio' che vincola il fix, in queste categorie:
   - **Contratti**: firme, tipi, eccezioni dichiarate/attese dai caller
     (`api.py:12 si aspetta che connect() sollevi ConnectionError, non ritorni None`)
   - **Invarianti dei dati**: assunzioni su forma/stato
     (`db.py:30: pool inizializzato prima di connect — mai None dopo setup()`)
   - **Comportamenti attesi**: cosa fissano i test correlati
     (`test_db.py:8: retry esattamente 3 volte prima di propagare`)
   - **Mappa del sintomo**: errore -> raise site -> percorso dati che ci arriva
3. Formato di output:

```
# carta del task
Q: <il bug, una riga>

## vincoli
1. [contratto]    <proposizione>          (file.py:riga)
2. [invariante]   <proposizione>          (file.py:riga)
3. [comportamento] <proposizione>         (test_x.py:riga)

## percorso del sintomo
<errore> nasce in <file:riga>, raggiunto da <catena breve>

## fuori slice ma sospetti (page fault suggeriti)
- <file/config> perche' <motivo>          (se nessuno: "nessuno")
```

## Regole

- Un vincolo senza citazione file:riga NON e' un vincolo: eliminalo o trovala.
- Massimo ~10 vincoli: se sono di piu', stai riassumendo, non estraendo.
- Niente parafrasi del codice: solo cio' che il fix puo' violare.
- La carta e' anche la checklist di review: dopo il fix, ripassala vincolo
  per vincolo (o passala a kernel-verify / al verifier agent).
