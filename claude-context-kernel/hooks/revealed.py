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
"""
from __future__ import annotations

import glob
import json
import os
import sys

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


def pick_transcripts(args: list[str]) -> list[str]:
    paths: list[str] = []
    for a in args:
        if os.path.isdir(a):
            paths.extend(sorted(glob.glob(os.path.join(a, "*.jsonl"))))
        elif os.path.isfile(a):
            paths.append(a)
    if not paths and not args:
        allt = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
        allt.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        paths = allt[:DEFAULT_LAST]
    return paths


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    paths = pick_transcripts(args)
    if not paths:
        print("nessun transcript trovato", file=sys.stderr)
        return 1
    results = [mine_transcript(p) for p in paths]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    print("\n\n".join(render(r) for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
