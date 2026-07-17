#!/usr/bin/env python3
"""
slice.py — proiezione FORMALE del codice: backward reachability slice.

Uso:
    python3 slice.py <file.py> <simbolo> [<simbolo2> ...]

Stampa solo le definizioni top-level raggiungibili dai simboli target sul
grafo def-use (piu' gli import usati). Cio' che non e' raggiungibile e' nel
kernel della mappa "comportamento del target" e non puo' cambiarne il senso.
Deterministico, answer-preserving per costruzione rispetto a quei simboli.
Solo Python. Per altri linguaggi: fallback = file intero.
"""
from __future__ import annotations

import ast
import sys

# Stream a UTF-8: su Windows il default e' la codepage locale. No-op su
# POSIX. Mai fatale.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                          # noqa: BLE001
        pass


def bound_names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        out: set[str] = set()
        for t in node.targets:
            out |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
        return out
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    if isinstance(node, ast.Import):
        return {(a.asname or a.name.split(".")[0]) for a in node.names}
    if isinstance(node, ast.ImportFrom):
        return {(a.asname or a.name) for a in node.names}
    return set()


def free_names(node: ast.AST) -> set[str]:
    local: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local |= {a.arg for a in n.args.args + n.args.kwonlyargs}
            if n.args.vararg:
                local.add(n.args.vararg.arg)
            if n.args.kwarg:
                local.add(n.args.kwarg.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            local.add(n.id)
    used = {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return used - local


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("uso: slice.py <file.py> <simbolo> [...]", file=sys.stderr)
        return 2
    path, targets = argv[1], set(argv[2:])
    src = open(path, encoding="utf-8").read()

    if not path.endswith(".py"):
        print(src)  # fallback: nessuna semantica -> file intero
        return 0

    tree = ast.parse(src)
    units = []
    for i, node in enumerate(tree.body):
        b = bound_names(node)
        if not b:
            continue
        units.append((i, node, b, free_names(node) - b,
                      isinstance(node, (ast.Import, ast.ImportFrom))))
    name_to_key = {n: i for i, _, b, _, _ in units for n in b}
    by_key = {i: (node, b, uses, is_imp) for i, node, b, uses, is_imp in units}

    seeds = {name_to_key[t] for t in targets if t in name_to_key}
    if not seeds:
        print(src)  # target ignoto: fail-safe = file intero
        return 0

    keep, frontier = set(seeds), set(seeds)
    while frontier:
        nxt = set()
        for k in frontier:
            for u in by_key[k][2]:
                dep = name_to_key.get(u)
                if dep is not None and dep not in keep and not by_key[dep][3]:
                    keep.add(dep)
                    nxt.add(dep)
        frontier = nxt

    used_names: set[str] = set()
    for k in keep:
        used_names |= by_key[k][2]
    for k, (node, b, uses, is_imp) in by_key.items():
        if is_imp and (b & used_names):
            keep.add(k)

    kept = [by_key[k][0] for k in sorted(keep)]
    print("\n\n\n".join(ast.unparse(n) for n in kept))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
