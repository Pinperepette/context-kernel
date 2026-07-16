---
name: kernel-verify
description: Verifica se una compressione/proiezione del contesto ha preservato la risposta (answer-invariance A(x) = A(pi(x))). Usa la sessione corrente per rispondere e giudicare — nessuna chiave API, nessun costo extra oltre l'abbonamento.
disable-model-invocation: false
effort: medium
---

# kernel-verify — answer-invariance in-sessione (zero chiavi)

Serve a rispondere a una sola domanda: **la versione compressa/proiettata del
contesto porta alla stessa risposta di quella completa?** Cioe' `A(x) = A(pi(x))`.

Questo controllo **non usa API ne' chiavi**: lo esegui tu, Claude, dentro la
sessione — quindi pesa solo sull'abbonamento gia' attivo.

## Input

L'utente ti fornisce (o indica dove trovarli):
1. un **task/domanda** `Q`;
2. il **contesto completo** `x`;
3. il **contesto ridotto** `pi(x)` (output di `compress.py`, dello slicer, o
   di un proiettore `span(Q)`).

## Procedura (falla in silenzio, poi riporta solo il verdetto)

1. Rispondi a `Q` usando **solo** `x`. Chiama questa `A(x)`.
2. Rispondi a `Q` usando **solo** `pi(x)`. Chiama questa `A(pi(x))`.
   Trattale come due contesti separati: non lasciare che `x` "riempia i buchi"
   di `pi(x)`.
3. Confronta `A(x)` e `A(pi(x))` **nel merito** (stessa conclusione, stessi
   fatti rilevanti). Ignora differenze di forma, lunghezza o parole.

## Output

Riporta in modo compatto:
- **INVARIANTE: si/no**
- se **no**: quale informazione presente in `x` e' andata persa in `pi(x)` e
  ha cambiato la risposta (indica l'unita'/riga mancante).
- una riga di verdetto (es. "stessa risposta: 30s di timeout" oppure
  "persa: il limite upload del Pro, ora la risposta e' incompleta").

## A cosa serve

E' il gate che trasforma la **compressione euristica** (conservativa, non
provabile) in una misura verificata *per quel task*. Usalo per:
- tarare quanto puoi comprimere prima che l'invarianza si rompa (il "ginocchio"
  della curva rate-distortion di `span_rd.py`);
- validare a campione l'output del compressore su casi delicati.

Nota: lo slicer del codice (`kernel-slice`) e' gia' answer-preserving *per
costruzione* — su quello questo controllo e' ridondante. Serve soprattutto sul
testo/documenti, dove la proiezione e' empirica.
