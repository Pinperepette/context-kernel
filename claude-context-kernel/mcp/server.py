#!/usr/bin/env python3
"""
server.py — server MCP (stdio) che espone lo slicer formale come tool.

Perche' MCP: e' l'unico standard cross-tool ratificato. Questo server gira
identico su Claude Code, Codex, Cursor, Gemini CLI, Zed... senza glue diversa.
Espone un solo tool esplicito: `kernel_slice(file, symbols)`.

Implementazione JSON-RPC 2.0 su stdio, newline-delimited, ZERO dipendenze
(niente `pip install mcp`): basta python3. Il tool riusa lo slice.py gia'
testato, invocandolo come subprocess.

NB: gli hook (compressione/rewrite) NON passano di qui — restano hook, perche'
l'MCP non puo' intercettare l'output dei tool built-in. Qui c'e' solo lo slice.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

# Stream a UTF-8: su Windows il default e' la codepage locale, l'harness
# parla UTF-8. Su POSIX e' un no-op. Mai fatale.
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                          # noqa: BLE001
        pass

SLICE = os.path.join(
    os.path.dirname(__file__), "..", "skills", "kernel-slice", "scripts", "slice.py"
)
REPO_SLICE = os.path.join(
    os.path.dirname(__file__), "..", "skills", "kernel-repo-slice", "scripts",
    "repo_slice.py"
)
PROTO_DEFAULT = "2025-06-18"

TOOL = {
    "name": "kernel_slice",
    "description": (
        "Estrae la fetta minimale di un file Python rilevante per uno o piu' "
        "simboli (funzioni/classi), scartando tutto cio' che non puo' "
        "influenzarne il comportamento (backward reachability slice sul grafo "
        "def-use). Answer-preserving per costruzione. Usalo al posto di leggere "
        "un file grande quando ti interessa solo un simbolo specifico."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Percorso del file .py"},
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Nomi dei simboli target (almeno uno)",
            },
        },
        "required": ["file", "symbols"],
        "additionalProperties": False,
    },
}

TOOL_REPO = {
    "name": "kernel_repo_slice",
    "description": (
        "Proietta un intero repository sul working set rilevante per un bug: "
        "dato un sintomo (stack trace, messaggio d'errore, path), costruisce "
        "il grafo degli import e tiene solo seed + dipendenze transitive + "
        "importatori vicini + test correlati. Ritorna un manifest ordinato con "
        "le motivazioni; cio' che e' fuori slice resta recuperabile on demand "
        "(page fault). Usalo PRIMA di esplorare un repo grande per un bug."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "Root del repository"},
            "symptom": {
                "type": "string",
                "description": "Stack trace / messaggio d'errore / descrizione col path",
            },
            "seeds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File seed espliciti (opzionale, in aggiunta al sintomo)",
            },
        },
        "required": ["repo", "symptom"],
        "additionalProperties": False,
    },
}


def run_slice(args: dict) -> dict:
    file = args.get("file", "")
    symbols = args.get("symbols") or []
    if not file or not symbols:
        return _err_content("Servono 'file' e almeno un elemento in 'symbols'.")
    if not os.path.exists(file):
        return _err_content(f"File non trovato: {file}")
    try:
        out = subprocess.run(
            [sys.executable, SLICE, file, *symbols],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except Exception as e:                       # noqa: BLE001
        return _err_content(f"Errore nell'esecuzione dello slicer: {e}")
    if out.returncode != 0:
        return _err_content(out.stderr.strip() or "slicer fallito")
    return {"content": [{"type": "text", "text": out.stdout}], "isError": False}


def run_repo_slice(args: dict) -> dict:
    repo = args.get("repo", "")
    symptom = args.get("symptom", "")
    seeds = args.get("seeds") or []
    if not repo or not symptom:
        return _err_content("Servono 'repo' e 'symptom'.")
    if not os.path.isdir(repo):
        return _err_content(f"Repo non trovato: {repo}")
    cmd = [sys.executable, REPO_SLICE, repo, "--symptom", symptom]
    for s in seeds:
        cmd += ["--seed", s]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             encoding="utf-8", errors="replace",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except Exception as e:                       # noqa: BLE001
        return _err_content(f"Errore nell'esecuzione del repo slicer: {e}")
    if out.returncode != 0:
        return _err_content(out.stderr.strip() or "repo slicer fallito")
    text = out.stdout
    if out.stderr.strip():                       # es. "nessun seed": va mostrato
        text = out.stderr.strip() + "\n\n" + text
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err_content(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def handle(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        proto = (req.get("params") or {}).get("protocolVersion", PROTO_DEFAULT)
        return _ok(rid, {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "context-kernel", "version": "0.1.0"},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notifica: nessuna risposta

    if method == "ping":
        return _ok(rid, {})

    if method == "tools/list":
        return _ok(rid, {"tools": [TOOL, TOOL_REPO]})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if name == TOOL["name"]:
            return _ok(rid, run_slice(params.get("arguments") or {}))
        if name == TOOL_REPO["name"]:
            return _ok(rid, run_repo_slice(params.get("arguments") or {}))
        return _err(rid, -32602, f"tool sconosciuto: {name}")

    if rid is None:
        return None  # notifica sconosciuta: ignora
    return _err(rid, -32601, f"metodo non gestito: {method}")


def _ok(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
