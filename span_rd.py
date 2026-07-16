"""
span_rd.py — definizione operativa di span(Q) e curva rate-distortion.

Concetto (framing di Hilbert, versione DISCRETA e implementabile):
  * il contesto C e' un insieme di unita' u_1..u_n (qui: paragrafi);
  * il task Q definisce un sottospazio span(Q) generato dagli embedding di
    alcune "sonde di rilevanza" (la query + eventuali facet);
  * la parte utile di u_i e' la sua PROIEZIONE ORTOGONALE su span(Q):
        score(u_i) = || P_Q e(u_i) || / || e(u_i) ||   in [0,1]
    = quanta "energia" dell'unita' vive nel sottospazio del task;
  * il proiettore discreto tiene le unita' con score alto entro un budget di
    token, scarta le quasi-ortogonali.

NON proiettiamo un vettore da ridare all'LLM (impossibile: l'embedding non e'
invertibile). Proiettiamo la SELEZIONE delle unita' d'ingresso guidata
dall'allineamento a span(Q). Questa e' la versione black-box-compatibile.

DISTORSIONE (asse y): offline usiamo la *sufficienza* come oracolo fedele: se
l'unita' che contiene la risposta viene proiettata via, la risposta cambia di
sicuro (D=1 per quel task). Per la distorsione SEMANTICA (A(C) ?= A(P_Q(C)))
non serve alcuna chiave: si misura in-sessione con lo skill `kernel-verify`,
usando l'abbonamento (e' Claude Code stesso a rispondere e giudicare).

RATE (asse x): frazione di token MANDATI NEL KERNEL (rimossi).

Confrontiamo la proiezione su span(Q) col baseline "troncamento posizionale"
(tieni i primi paragrafi) per mostrare che la proiezione compra margine.
"""
from __future__ import annotations

import os
import numpy as np

from kernel_projector import estimate_tokens

EMB_MODEL = os.environ.get("CK_EMB_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


# --------------------------------------------------------------------------
# Corpus di prova: doc "prodotto" con fatti sparsi + rumore (SEO/boilerplate/dup)
# --------------------------------------------------------------------------
CORPUS = [
    "Benvenuto nella documentazione di Acme Cloud, la piattaforma leader per il deploy moderno.",  # 0 SEO
    "Acme Cloud e' scelto da migliaia di team in tutto il mondo per la sua affidabilita'.",         # 1 SEO/dup
    "Il piano Free include 3 progetti e 100 GB di banda al mese.",                                  # 2 FATTO
    "Per iniziare, crea un account e verifica la tua email.",                                       # 3 boilerplate
    "Il limite di upload per singolo file e' 500 MB sul piano Free e 5 GB sul piano Pro.",          # 4 FATTO
    "La nostra missione e' rendere il cloud semplice, veloce e accessibile a tutti.",               # 5 SEO
    "Il timeout predefinito delle richieste API e' 30 secondi, configurabile fino a 300.",          # 6 FATTO
    "Acme Cloud e' scelto da migliaia di team per affidabilita' e velocita'.",                      # 7 dup di 1
    "I webhook vengono ritentati fino a 5 volte con backoff esponenziale prima di fallire.",        # 8 FATTO
    "Contattaci per una demo e scopri perche' Acme Cloud fa la differenza.",                        # 9 SEO/CTA
    "Le chiavi API scadono dopo 90 giorni e vanno ruotate dal pannello Impostazioni.",              # 10 FATTO
    "Grazie per aver scelto Acme Cloud: siamo qui per aiutarti a crescere.",                        # 11 boilerplate
    # --- distrattori ad alta affinita' (near-miss): confondono il proiettore ---
    "Il piano Pro offre banda illimitata, 50 progetti e supporto prioritario.",                     # 12 distrattore banda
    "Il rate limit delle API e' di 1000 richieste al minuto per chiave.",                           # 13 distrattore API
    "Il limite di upload sul piano Enterprise e' negoziabile con il commerciale.",                  # 14 distrattore upload
    "I job in background hanno un timeout massimo di 15 minuti sul piano Pro.",                      # 15 distrattore timeout
    "Le notifiche email vengono inviate al massimo una volta all'ora per evitare spam.",            # 16 distrattore webhook/retry
    "La fatturazione e' mensile e le chiavi di pagamento sono gestite da Stripe.",                  # 17 distrattore chiavi
]

# (domanda, indice/i del paragrafo-risposta, sonde per span(Q))
QA = [
    ("Qual e' il limite di banda del piano Free?", 2,
     ["limite di banda piano Free", "quanta banda gratis", "GB al mese Free"]),
    ("Qual e' la dimensione massima di upload di un file sul piano Pro?", 4,
     ["dimensione massima upload file", "limite upload Pro", "MB GB per file"]),
    ("Quanto dura il timeout predefinito delle API?", 6,
     ["timeout richieste API", "secondi timeout default", "durata timeout"]),
    ("Quante volte vengono ritentati i webhook?", 8,
     ["retry webhook", "tentativi webhook backoff", "quante volte ritentati"]),
    ("Dopo quanto scadono le chiavi API?", 10,
     ["scadenza chiavi API", "durata API key giorni", "rotazione chiavi"]),
    # multi-unita': serve SIA banda SIA upload del Free
    ("Riassumi i limiti del piano Free (banda e upload).", [2, 4],
     ["limiti del piano Free", "banda e upload gratis", "restrizioni account Free"]),
    # mismatch lessicale: la risposta e' formulata diversamente dalle sonde
    ("Per quanto tempo restano valide le credenziali prima di doverle cambiare?", 10,
     ["validita' credenziali", "quando cambiare le credenziali", "durata accesso"]),
]


# --------------------------------------------------------------------------
# Embeddings + span(Q) come sottospazio ortonormale
# --------------------------------------------------------------------------
def load_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMB_MODEL)


def embed(model, texts: list[str]) -> np.ndarray:
    return np.asarray(model.encode(texts, normalize_embeddings=False), dtype=np.float64)


def span_basis(model, probes: list[str]) -> np.ndarray:
    """Base ortonormale B (d x k) di span(Q) = span{ e(sonda_i) }.
    Ortonormalizzata via QR. k = numero di sonde indipendenti."""
    P = embed(model, probes)                     # (k, d)
    Q, _ = np.linalg.qr(P.T)                      # colonne ortonormali (d, k)
    return Q


def alignment(units_emb: np.ndarray, B: np.ndarray) -> np.ndarray:
    """score_i = ||P_Q e(u_i)|| / ||e(u_i)||  in [0,1]. P_Q = B B^T."""
    coords = units_emb @ B                        # (n, k) coordinate nel sottospazio
    proj_norm = np.linalg.norm(coords, axis=1)
    unit_norm = np.linalg.norm(units_emb, axis=1) + 1e-12
    return proj_norm / unit_norm


# --------------------------------------------------------------------------
# Proiettore discreto: tieni le unita' ad alto score entro un budget di token
# --------------------------------------------------------------------------
def kept_by_projection(order: list[int], keep_tokens: int, tokens: list[int]) -> set[int]:
    kept, used = set(), 0
    for i in order:
        if used + tokens[i] > keep_tokens and kept:
            break
        kept.add(i)
        used += tokens[i]
    return kept


def rate_distortion(model) -> None:
    units = CORPUS
    tokens = [estimate_tokens(u) for u in units]
    total = sum(tokens)
    E = embed(model, units)

    # ordinamento per proiezione su span(Q), per ogni task
    proj_order: dict[int, list[int]] = {}
    for qi, (_, _, probes) in enumerate(QA):
        B = span_basis(model, probes)
        scores = alignment(E, B)
        proj_order[qi] = list(np.argsort(-scores))
    pos_order = list(range(len(units)))            # baseline: ordine posizionale

    grid = [round(x, 2) for x in np.linspace(0.15, 1.0, 18)]
    print(f"Corpus: {len(units)} paragrafi, {total} token totali.  "
          f"Distorsione = frazione di domande diventate NON risolvibili "
          f"(unita'-risposta proiettata via).\n")
    print(f"{'rate(rimosso)':>13} | {'span(Q) proj':>14} | {'baseline pos.':>14}")
    print("-" * 48)

    for keep_frac in grid:
        keep_tokens = int(keep_frac * total)
        rate = 1 - keep_frac
        d_proj = _distortion(proj_order, keep_tokens, tokens, per_task=True)
        d_base = _distortion({qi: pos_order for qi in range(len(QA))},
                             keep_tokens, tokens, per_task=True)
        suf_p, suf_b = 1 - d_proj, 1 - d_base
        print(f"{rate:>12.0%} | {_bar(suf_p)} | {_bar(suf_b)}")


def _required(gold) -> set[int]:
    return set(gold) if isinstance(gold, (list, tuple)) else {gold}


def _distortion(order_by_q, keep_tokens, tokens, per_task) -> float:
    lost = 0
    for qi, (_, gold, _) in enumerate(QA):
        kept = kept_by_projection(order_by_q[qi], keep_tokens, tokens)
        if not _required(gold).issubset(kept):    # persa se manca UNA unita' richiesta
            lost += 1
    return lost / len(QA)


def _bar(suf: float) -> str:
    n = int(round(suf * 10))
    return f"{'#' * n}{'.' * (10 - n)} {suf:>4.0%}"


# --------------------------------------------------------------------------
# Export del contesto proiettato per una domanda, a un dato keep-fraction.
# Utile per passarlo allo skill `kernel-verify` (verifica semantica in-sessione,
# senza chiave: e' Claude Code a rispondere e giudicare).
# --------------------------------------------------------------------------
def projected_context(model, qi: int, keep_frac: float) -> tuple[str, str]:
    _, _, probes = QA[qi]
    tokens = [estimate_tokens(u) for u in CORPUS]
    E = embed(model, CORPUS)
    B = span_basis(model, probes)
    order = list(np.argsort(-alignment(E, B)))
    kept = kept_by_projection(order, int(keep_frac * sum(tokens)), tokens)
    full = "\n".join(CORPUS)
    proj = "\n".join(CORPUS[i] for i in sorted(kept))
    return full, proj


if __name__ == "__main__":
    m = load_embedder()
    rate_distortion(m)
    print("\n[distorsione semantica: usa lo skill `kernel-verify` in-sessione "
          "(nessuna chiave, usa l'abbonamento)]")
