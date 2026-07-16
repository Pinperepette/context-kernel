"""
kernel_projector — proiezione answer-preserving del contesto, prima dell'LLM.

Idea centrale (vedi README.md per la formalizzazione completa):

    Sia A: X -> Y la funzione-risposta (l'LLM che risolve un task).
    Definiamo x ~ x'  <=>  A(x) = A(x').
    Un *proiettore* pi: X -> X e' idempotente (pi(pi(x)) = pi(x)) e
    answer-preserving:  A(pi(x)) = A(x)  per ogni x.
    Tutto cio' che pi rimuove sta nel "kernel" della mappa A: non puo'
    influenzare la risposta. L'LLM lavora su pi(x), non su x.

Due regimi:
  * Proiettore FORMALE (codice): uno slice di raggiungibilita' sull'AST.
    Answer-preserving *per costruzione* rispetto a "cosa fa il simbolo S":
    cio' che S non puo' raggiungere non puo' cambiarne il comportamento.
  * Proiettore EMPIRICO (testo): riduzione euristica + verifica di
    answer-invariance in-sessione (skill kernel-verify, senza chiave API).

Questo modulo non dipende da rete o API: e' pura analisi statica.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Protocol


# --------------------------------------------------------------------------
# Metriche
# --------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    """Stima offline dei token (~4 char/token). Deterministica, nessuna rete."""
    return max(1, len(text) // 4)


@dataclass
class ProjectionResult:
    """Risultato di una proiezione pi(x)."""

    original: str
    projected: str
    kept: list[str] = field(default_factory=list)      # unita' mantenute (in Im)
    removed: list[str] = field(default_factory=list)    # unita' rimosse (nel kernel)

    @property
    def tokens_before(self) -> int:
        return estimate_tokens(self.original)

    @property
    def tokens_after(self) -> int:
        return estimate_tokens(self.projected)

    @property
    def compression_ratio(self) -> float:
        """Frazione di informazione (token) mandata nel kernel."""
        if self.tokens_before == 0:
            return 0.0
        return 1.0 - self.tokens_after / self.tokens_before

    def summary(self) -> str:
        return (
            f"token: {self.tokens_before} -> {self.tokens_after} "
            f"(-{self.compression_ratio:.0%})  |  "
            f"kept={len(self.kept)} removed={len(self.removed)}"
        )


class Projector(Protocol):
    """Un proiettore pi: X -> X, dato un task/query."""

    def project(self, x: str, query: str) -> ProjectionResult: ...


# --------------------------------------------------------------------------
# Proiettore FORMALE: slice di raggiungibilita' su codice Python
# --------------------------------------------------------------------------
class PythonSlicer:
    """Backward reachability slice a livello di definizioni top-level.

    Dato un modulo Python e una query che nomina uno o piu' simboli target,
    mantiene solo le definizioni (funzioni, classi, assegnazioni, import)
    raggiungibili dai target sul grafo def-use, ed elimina il resto.

    Garanzia (per costruzione): il comportamento dei target dipende solo
    dalla chiusura transitiva delle loro dipendenze. Tutto cio' che non e'
    raggiungibile e' nel kernel della mappa "comportamento del target" e
    non puo' cambiare la risposta a domande su quei target.
    L'over-approssimazione (tenere qualcosa in piu') e' sempre sicura:
    riduce la compressione, non l'invarianza.
    """

    def project(self, x: str, query: str) -> ProjectionResult:
        tree = ast.parse(x)
        units = _top_level_units(tree)
        name_to_unit = {n: u for u in units for n in u.binds}

        targets = _targets_from_query(query, name_to_unit)
        if not targets:
            # nessun target riconosciuto: proiezione identita' (fail-safe)
            return ProjectionResult(x, x, kept=[u.label for u in units])

        keep = _reachable(targets, units, name_to_unit)

        kept_units = [u for u in units if u.key in keep]
        removed_units = [u for u in units if u.key not in keep]

        projected = "\n\n\n".join(ast.unparse(u.node) for u in kept_units) + "\n"
        return ProjectionResult(
            original=x,
            projected=projected,
            kept=[u.label for u in kept_units],
            removed=[u.label for u in removed_units],
        )


@dataclass
class _Unit:
    """Una definizione top-level e le sue relazioni nel grafo def-use."""

    node: ast.stmt
    binds: set[str]          # nomi che questa unita' introduce
    uses: set[str]           # nomi liberi che questa unita' referenzia
    label: str
    key: int

    @property
    def is_import(self) -> bool:
        return isinstance(self.node, (ast.Import, ast.ImportFrom))


def _top_level_units(tree: ast.Module) -> list[_Unit]:
    units: list[_Unit] = []
    for i, node in enumerate(tree.body):
        binds = _bound_names(node)
        if not binds:
            continue
        uses = _free_names(node) - binds
        label = _label(node, binds)
        units.append(_Unit(node=node, binds=binds, uses=uses, label=label, key=i))
    return units


def _bound_names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        names: set[str] = set()
        for t in node.targets:
            names |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
        return names
    if isinstance(node, (ast.AnnAssign,)) and isinstance(node.target, ast.Name):
        return {node.target.id}
    if isinstance(node, ast.Import):
        return {(a.asname or a.name.split(".")[0]) for a in node.names}
    if isinstance(node, ast.ImportFrom):
        return {(a.asname or a.name) for a in node.names}
    return set()


def _free_names(node: ast.AST) -> set[str]:
    """Nomi referenziati in Load, meno quelli legati localmente (params,
    assegnazioni interne). Over-approssimare e' sicuro; qui puliamo i casi
    ovvi per migliorare la compressione."""
    local: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local |= {a.arg for a in n.args.args}
            local |= {a.arg for a in n.args.kwonlyargs}
            if n.args.vararg:
                local.add(n.args.vararg.arg)
            if n.args.kwarg:
                local.add(n.args.kwarg.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store,)):
            local.add(n.id)

    used = {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return used - local


def _label(node: ast.stmt, binds: set[str]) -> str:
    kind = {
        ast.FunctionDef: "def",
        ast.AsyncFunctionDef: "async def",
        ast.ClassDef: "class",
        ast.Import: "import",
        ast.ImportFrom: "from-import",
        ast.Assign: "assign",
        ast.AnnAssign: "assign",
    }.get(type(node), "stmt")
    return f"{kind} {', '.join(sorted(binds))}"


def _targets_from_query(query: str, name_to_unit: dict[str, _Unit]) -> set[str]:
    """Riconosce i simboli nominati nella query che esistono nel modulo."""
    tokens = set(_split_identifiers(query))
    return {name for name in name_to_unit if name in tokens}


def _split_identifiers(text: str) -> list[str]:
    out, cur = [], []
    for ch in text:
        if ch.isalnum() or ch == "_":
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _reachable(
    targets: set[str], units: list[_Unit], name_to_unit: dict[str, _Unit]
) -> set[int]:
    """BFS sulla chiusura transitiva def-use a partire dai target.
    Gli import sono tenuti solo se un'unita' mantenuta usa il nome importato."""
    frontier = {name_to_unit[t].key for t in targets}
    keep = set(frontier)
    key_to_unit = {u.key: u for u in units}

    while frontier:
        nxt: set[int] = set()
        for k in frontier:
            for used in key_to_unit[k].uses:
                dep = name_to_unit.get(used)
                if dep and dep.key not in keep and not dep.is_import:
                    keep.add(dep.key)
                    nxt.add(dep.key)
        frontier = nxt

    # import: mantieni solo quelli effettivamente usati dalle unita' tenute
    used_names: set[str] = set()
    for k in keep:
        used_names |= key_to_unit[k].uses
    for u in units:
        if u.is_import and (u.binds & used_names):
            keep.add(u.key)

    return keep


# --------------------------------------------------------------------------
# Proiettore EMPIRICO: testo (firme, disclaimer, quote gia' risolte)
# --------------------------------------------------------------------------
class EmailProjector:
    """Rimozione euristica di firme, disclaimer e thread citati.

    Non c'e' garanzia formale: e' answer-preserving *empiricamente* e va
    validato in-sessione con lo skill kernel-verify (senza chiave API).
    """

    SIGNATURE_MARKERS = ("-- ", "sent from my", "inviato da", "confidential",
                         "this email and any attachments", "cordiali saluti",
                         "best regards", "kind regards")

    def project(self, x: str, query: str) -> ProjectionResult:
        kept_lines, removed_lines = [], []
        in_signature = False
        for line in x.splitlines():
            low = line.strip().lower()
            if line.strip() == "--" or low.startswith("-- "):
                in_signature = True
            is_quote = line.lstrip().startswith(">")
            is_disclaimer = any(m in low for m in self.SIGNATURE_MARKERS)
            if in_signature or is_quote or is_disclaimer:
                removed_lines.append(line)
            else:
                kept_lines.append(line)
        return ProjectionResult(
            original=x,
            projected="\n".join(kept_lines).strip() + "\n",
            kept=[f"line: {l[:40]}" for l in kept_lines if l.strip()],
            removed=[f"line: {l[:40]}" for l in removed_lines if l.strip()],
        )
