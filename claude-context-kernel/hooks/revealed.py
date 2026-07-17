#!/usr/bin/env python3
"""
revealed.py — T5: miner della RILEVANZA RIVELATA.

La versione onesta (e gratis) dell'ablazione del contesto: invece di
intervenire (N pezzi = N+1 chiamate) si OSSERVA il transcript — quali file
del working set il modello ha davvero aperto, quali ha aperto FUORI slice,
quali page fault ha fatto dopo un'elisione. Risponde con numeri alla domanda
dell'articolo: "quanto sono costati i fault?".

Output: report deterministico con SUGGERIMENTI che un umano applica (mai
tuning automatico: la telemetria suggerisce, il determinismo resta intatto).

Uso:
  python3 revealed.py transcript.jsonl [...]   # transcript espliciti
  python3 revealed.py directory/               # tutti i .jsonl dentro
  python3 revealed.py                          # gli ultimi 5 sotto ~/.claude/projects
  python3 revealed.py --json ...               # output macchina
  python3 revealed.py --aggregate [--last N]   # vista LONGITUDINALE: i pattern
                                               # che un singolo transcript non
                                               # mostra (fault ricorrenti sullo
                                               # stesso file, seed persi in piu'
                                               # sessioni) -> proposta di config
                                               # che l'umano applica
  python3 revealed.py --aggregate --apply-rates
                                               # ATTUAZIONE ESPLICITA dei tassi:
                                               # scrive i tassi per-categoria
                                               # (estensione) che compress.py
                                               # legge. Direzione unica: solo
                                               # RILASSARE dove i fault sono
                                               # misurati e ricorrenti (>=2),
                                               # mai stringere. Il lancio e'
                                               # dell'umano: niente auto-tuning
                                               # silenzioso.
  python3 revealed.py --aggregate --write-priors
                                               # ATTUAZIONE ESPLICITA dei prior
                                               # T5 -> T2: seed candidati e file
                                               # freddi (ricorrenza >=2) scritti
                                               # dove repo_slice.py li legge.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

PROJECTS_DIR = os.path.expanduser(
    os.environ.get("CK_PROJECTS_DIR", "~/.claude/projects"))
DEFAULT_LAST = int(os.environ.get("CK_REVEALED_LAST", "5"))

MANIFEST_MARK = "## seed (dal sintomo)"
ELIDED_MARK = "copia ELISA"
INVARIATO_MARK = "file INVARIATO dall'ultima lettura"


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _strings(obj, depth: int = 0):
    """Tutte le stringhe annidate di un oggetto JSON (profondita' limitata)."""
    if depth > 6:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, depth + 1)


def _blocks(obj, depth: int = 0):
    """Tutti i dict con chiave "type" (content block) annidati."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        if "type" in obj:
            yield obj
        for v in obj.values():
            yield from _blocks(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _blocks(v, depth + 1)


def manifest_files(text: str) -> tuple[list[str], str | None]:
    """(file del manifest, repo) dalle sezioni seed + slice."""
    files: list[str] = []
    repo = None
    section = None
    for line in text.split("\n"):
        if line.startswith("repo: "):
            repo = line[len("repo: "):].strip()
        if line.startswith("## "):
            section = line
            continue
        if section is None or "fuori slice" in section:
            continue
        if line.startswith("- ") and not line.startswith(("- …", "- (")):
            f = line[2:].split()[0]
            if f not in files:
                files.append(f)
    return files, repo


def mine_transcript(path: str) -> dict:
    """Un passaggio sul JSONL: manifest iniettati, Read fatte, elisioni,
    page fault (rilettura dello stesso file dopo una copia ELISA)."""
    slice_files: list[str] = []
    repo = None
    reads: list[str] = []                      # file_path in ordine
    read_by_id: dict[str, str] = {}            # tool_use_id -> file_path
    elided: set[str] = set()                   # file consegnati ELISI
    faults: list[tuple[str, int]] = []         # (file, ~token della rilettura)
    invariato = 0

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                if not raw.strip():
                    continue
                try:
                    d = json.loads(raw)
                except Exception:              # noqa: BLE001
                    continue
                for b in _blocks(d):
                    btype = b.get("type")
                    if btype == "tool_use" and b.get("name") == "Read":
                        fp = (b.get("input") or {}).get("file_path")
                        if isinstance(fp, str) and fp:
                            if fp in elided:   # rilettura post-elisione
                                faults.append((fp, 0))
                                elided.discard(fp)
                            reads.append(fp)
                            if b.get("id"):
                                read_by_id[b["id"]] = fp
                    elif btype == "tool_result":
                        fp = read_by_id.get(b.get("tool_use_id") or "")
                        text = "\n".join(_strings(b.get("content")))
                        if fp:
                            if ELIDED_MARK in text:
                                elided.add(fp)
                            elif faults and faults[-1][0] == fp and faults[-1][1] == 0:
                                # la rilettura integrale: misura il costo
                                faults[-1] = (fp, est_tokens(text))
                            if INVARIATO_MARK in text:
                                invariato += 1
                # manifest T2 iniettati (additionalContext o output slicer)
                if MANIFEST_MARK in raw:
                    for s in _strings(d):
                        if MANIFEST_MARK in s:
                            slice_files, repo = manifest_files(s)
                            break
    except Exception:                          # noqa: BLE001
        pass

    read_set = set(reads)

    def in_slice(fp: str) -> bool:
        norm = os.path.normpath(fp)
        return any(norm.endswith(os.sep + os.path.normpath(sf))
                   or os.path.normpath(sf) == norm
                   for sf in slice_files)

    opened = [sf for sf in slice_files
              if any(os.path.normpath(fp).endswith(os.sep + os.path.normpath(sf))
                     or os.path.normpath(sf) == os.path.normpath(fp)
                     for fp in read_set)]
    never = [sf for sf in slice_files if sf not in opened]
    outside = sorted({fp for fp in read_set if slice_files and not in_slice(fp)})
    return {
        "transcript": path,
        "repo": repo,
        "slice_files": slice_files,
        "opened": opened,
        "never_opened": never,
        "outside_slice": outside,
        "reads": len(reads),
        "faults": [{"file": f, "tokens": t} for f, t in faults],
        "fault_tokens": sum(t for _, t in faults),
        "invariato": invariato,
    }


def render(r: dict) -> str:
    out = [f"# rilevanza rivelata — {os.path.basename(r['transcript'])}"]
    if not r["slice_files"] and not r["reads"]:
        out.append("(nessuna slice T2 e nessuna Read nel transcript)")
        return "\n".join(out)
    if r["slice_files"]:
        n = len(r["slice_files"])
        out.append(f"manifest T2: {n} file"
                   + (f" (repo {r['repo']})" if r["repo"] else ""))
        out.append(f"- aperti dalla slice: {len(r['opened'])}/{n}")
        if r["never_opened"]:
            shown = ", ".join(r["never_opened"][:10])
            more = f" (+{len(r['never_opened']) - 10})" \
                if len(r["never_opened"]) > 10 else ""
            out.append(f"- MAI aperti: {shown}{more}")
            out.append("  -> suggerimento: se ricorre su piu' sessioni, il "
                       "prior e' largo — valuta meno importatori/profondita' "
                       "(il page fault resta come rete)")
        if r["outside_slice"]:
            shown = ", ".join(r["outside_slice"][:10])
            more = f" (+{len(r['outside_slice']) - 10})" \
                if len(r["outside_slice"]) > 10 else ""
            out.append(f"- aperti FUORI slice: {shown}{more}")
            out.append("  -> suggerimento: seed persi — se sono config/DI/"
                       "import dinamici, candidali ai seed dello slicer")
    else:
        out.append(f"nessun manifest T2 iniettato; Read totali: {r['reads']}")
    if r["faults"]:
        files = ", ".join(sorted({f['file'].split('/')[-1]
                                  for f in r["faults"]}))
        out.append(f"- page fault post-elisione: {len(r['faults'])} "
                   f"({files}) ~{r['fault_tokens']} token di riletture")
        out.append("  -> costo dell'elisione su questi file: se ricorre, "
                   "alza CK_MIN_TOKENS/CK_OUTLINE_MIN o usa # ck:raw li'")
    else:
        out.append("- page fault post-elisione: 0 (nessuna elisione e' "
                   "costata una rilettura)")
    if r["invariato"]:
        out.append(f"- riletture INVARIATE evitate: {r['invariato']}")
    return "\n".join(out)


def aggregate(results: list[dict]) -> dict:
    """Vista longitudinale su N transcript. Le soglie sono deliberatamente
    conservative: una proposta scatta solo su RICORRENZA (>=2 sessioni o >=2
    occorrenze), mai sull'episodio singolo — che il report per-transcript
    mostra gia'."""
    fault_files: dict[str, dict] = {}
    outside: dict[str, int] = {}
    never: dict[str, int] = {}
    manifests = 0
    tot_faults = 0
    tot_fault_tokens = 0
    tot_invariato = 0
    for r in results:
        if r["slice_files"]:
            manifests += 1
        seen_here: set[str] = set()
        for f in r["faults"]:
            fp = f["file"]
            d = fault_files.setdefault(
                fp, {"faults": 0, "tokens": 0, "transcripts": 0})
            d["faults"] += 1
            d["tokens"] += f["tokens"]
            tot_faults += 1
            tot_fault_tokens += f["tokens"]
            if fp not in seen_here:
                d["transcripts"] += 1
                seen_here.add(fp)
        for fp in r["outside_slice"]:
            outside[fp] = outside.get(fp, 0) + 1
        for sf in r["never_opened"]:
            never[sf] = never.get(sf, 0) + 1
        tot_invariato += r["invariato"]

    proposals: list[str] = []
    for fp, d in sorted(fault_files.items(),
                        key=lambda kv: (-kv[1]["tokens"], kv[0])):
        if d["transcripts"] >= 2 or d["faults"] >= 2:
            proposals.append(
                f"`# ck:raw` in {os.path.basename(fp)} (o alza "
                f"CK_MIN_TOKENS/CK_OUTLINE_MIN): {d['faults']} fault, "
                f"~{d['tokens']} token di riletture in "
                f"{d['transcripts']} sessioni — {fp}")
    for fp, n in sorted(outside.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= 2:
            proposals.append(
                f"candidalo ai seed dello slicer: {fp} "
                f"(aperto FUORI slice in {n} sessioni)")
    for sf, n in sorted(never.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= 2:
            proposals.append(
                f"prior largo: {sf} in slice ma MAI aperto in {n} manifest "
                "— valuta meno importatori/profondita'")
    return {
        "transcripts": len(results),
        "manifests": manifests,
        "faults": tot_faults,
        "fault_tokens": tot_fault_tokens,
        "invariato": tot_invariato,
        "fault_files": fault_files,
        "outside_recurrent": {f: n for f, n in outside.items() if n >= 2},
        "never_recurrent": {f: n for f, n in never.items() if n >= 2},
        "proposals": proposals,
    }


# --- attuazione esplicita (T5 -> T1 / T5 -> T2) ------------------------------
# Il default resta il report: la telemetria suggerisce. Questi writer sono il
# gesto dell'umano che applica — un comando, non un tuning silenzioso. Le
# soglie di ricorrenza (>=2 sessioni/occorrenze) sono le stesse dell'aggregato:
# mai attuare sull'episodio singolo. Direzione fail-safe: i tassi possono solo
# RILASSARE la compressione (mai stringerla: l'assenza di fault non prova
# l'assenza di distorsione — il fault e' visibile solo se il modello ha
# riletto); i prior possono solo AGGIUNGERE seed o FLAGGARE file freddi, mai
# escludere.

RATES_STATE = os.path.expanduser(
    os.environ.get("CK_RATES_STATE", "~/.context-kernel-rates.json"))
RATES_RAW_FAULTS = int(os.environ.get("CK_RATES_RAW_FAULTS", "4"))
RATES_RAW_TOKENS = int(os.environ.get("CK_RATES_RAW_TOKENS", "20000"))
RATES_SCALE = float(os.environ.get("CK_RATES_SCALE", "1.5"))
PRIORS_STATE = os.path.expanduser(
    os.environ.get("CK_PRIORS_STATE", "~/.context-kernel-priors.json"))


def rates_from_aggregate(a: dict) -> dict:
    """Tassi per-categoria (estensione del file) dai fault RICORRENTI.
    Fault pesanti -> raw (niente elisione); ricorrenti ma leggeri -> relax
    (scala HEAD/TAIL/soglia di un fattore >1)."""
    cats: dict[str, dict] = {}
    for fp, d in a["fault_files"].items():
        if d["transcripts"] < 2 and d["faults"] < 2:
            continue                           # mai sull'episodio singolo
        ext = os.path.splitext(fp)[1].lower() or "(noext)"
        c = cats.setdefault(ext, {"faults": 0, "tokens": 0})
        c["faults"] += d["faults"]
        c["tokens"] += d["tokens"]
    out: dict[str, dict] = {}
    for ext, c in sorted(cats.items()):
        if c["faults"] >= RATES_RAW_FAULTS or c["tokens"] >= RATES_RAW_TOKENS:
            out[ext] = {"mode": "raw", **c}
        else:
            out[ext] = {"mode": "relax", "scale": RATES_SCALE, **c}
    return out


def write_rates(a: dict) -> list[str]:
    """Scrive RATES_STATE per compress.py. Ritorna le righe di esito."""
    rates = rates_from_aggregate(a)
    if not rates:
        return ["tassi: nessun fault ricorrente — niente da scrivere"]
    payload = {"ts": time.time(), "transcripts": a["transcripts"],
               "categories": rates}
    tmp = f"{RATES_STATE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, RATES_STATE)
    lines = [f"tassi scritti in {RATES_STATE} (compress.py li legge):"]
    lines += [f"- {ext} -> {r['mode']}"
              + (f" x{r['scale']}" if r["mode"] == "relax" else "")
              + f" ({r['faults']} fault, ~{r['tokens']} token di riletture)"
              for ext, r in rates.items()]
    return lines


def priors_from_aggregate(a: dict, results: list[dict]) -> dict:
    """{repo: {seeds: [...], cold: [...]}} dai pattern RICORRENTI (>=2).
    seeds = aperti FUORI slice in piu' sessioni (path relativizzato al repo);
    cold = in slice ma MAI aperti in piu' manifest. L'associazione file->repo
    viene dai risultati per-transcript, MAI indovinata: un file che non si
    lascia attribuire con certezza resta fuori dai prior."""
    def _repo_of(fp: str, key: str) -> str | None:
        owners = {r["repo"] for r in results
                  if r.get("repo") and fp in r.get(key, ())}
        return owners.pop() if len(owners) == 1 else None

    out: dict[str, dict] = {}
    for fp, n in sorted(a["outside_recurrent"].items()):
        repo = _repo_of(fp, "outside_slice")
        if not repo:
            continue
        rel = fp[len(repo.rstrip("/") + "/"):] \
            if fp.startswith(repo.rstrip("/") + "/") else fp
        if not os.path.isabs(rel):
            out.setdefault(repo, {"seeds": [], "cold": []})[
                "seeds"].append({"path": rel, "sessions": n})
    for sf, n in sorted(a["never_recurrent"].items()):
        repo = _repo_of(sf, "never_opened")    # path gia' repo-relativo
        if repo:
            out.setdefault(repo, {"seeds": [], "cold": []})[
                "cold"].append({"path": sf, "sessions": n})
    return out


def write_priors(a: dict, results: list[dict]) -> list[str]:
    """Scrive PRIORS_STATE per repo_slice.py. Ritorna le righe di esito."""
    priors = priors_from_aggregate(a, results)
    if not priors:
        return ["prior: nessun pattern ricorrente con repo noto — "
                "niente da scrivere"]
    try:
        with open(PRIORS_STATE, encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict):
            st = {}
    except Exception:                          # noqa: BLE001
        st = {}
    lines = [f"prior scritti in {PRIORS_STATE} (repo_slice.py li legge):"]
    for repo, rec in priors.items():
        st[os.path.normpath(repo)] = {"ts": time.time(),
                                      "transcripts": a["transcripts"], **rec}
        lines.append(f"- {repo}: {len(rec['seeds'])} seed candidati, "
                     f"{len(rec['cold'])} file freddi")
    for k in sorted(st, key=lambda k: st[k].get("ts", 0))[:-8]:
        st.pop(k, None)                        # tieni gli ultimi 8 repo
    tmp = f"{PRIORS_STATE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, PRIORS_STATE)
    return lines


def render_aggregate(a: dict) -> str:
    out = [f"# rilevanza rivelata — AGGREGATO su {a['transcripts']} transcript"]
    out.append(f"manifest T2 visti: {a['manifests']}  |  page fault totali: "
               f"{a['faults']} (~{a['fault_tokens']} token di riletture)  |  "
               f"riletture INVARIATE evitate: {a['invariato']}")
    if a["proposals"]:
        out.append("")
        out.append("## proposta di config (applicala tu: la telemetria "
                   "suggerisce, mai auto-tuning)")
        out.extend(f"- {p}" for p in a["proposals"])
    else:
        out.append("nessun pattern ricorrente: niente da proporre "
                   "(le soglie scattano su >=2 sessioni/occorrenze)")
    return "\n".join(out)


def pick_transcripts(args: list[str], last: int = DEFAULT_LAST) -> list[str]:
    paths: list[str] = []
    for a in args:
        if os.path.isdir(a):
            paths.extend(sorted(glob.glob(os.path.join(a, "*.jsonl"))))
        elif os.path.isfile(a):
            paths.append(a)
    if not paths and not args:
        allt = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
        allt.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        paths = allt[:last]
    return paths


def main() -> int:
    argv = sys.argv[1:]
    as_json = "--json" in argv
    apply_rates = "--apply-rates" in argv
    write_priors_flag = "--write-priors" in argv
    do_aggregate = ("--aggregate" in argv or apply_rates or write_priors_flag)
    last = DEFAULT_LAST
    args: list[str] = []
    it = iter(argv)
    for a in it:
        if a in ("--json", "--aggregate", "--apply-rates", "--write-priors"):
            continue
        if a == "--last":
            try:
                last = int(next(it))
            except (StopIteration, ValueError):
                print("--last vuole un intero", file=sys.stderr)
                return 1
            continue
        args.append(a)
    paths = pick_transcripts(args, last)
    if not paths:
        print("nessun transcript trovato", file=sys.stderr)
        return 1
    results = [mine_transcript(p) for p in paths]
    if do_aggregate:
        agg = aggregate(results)
        extra: list[str] = []
        if apply_rates:
            extra += write_rates(agg)
        if write_priors_flag:
            extra += write_priors(agg, results)
        if as_json:
            if extra:
                agg["applied"] = extra
            print(json.dumps(agg, ensure_ascii=False, indent=1))
        else:
            out = render_aggregate(agg)
            if extra:
                out += "\n\n## attuazione esplicita\n" + "\n".join(extra)
            print(out)
        return 0
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    print("\n\n".join(render(r) for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
