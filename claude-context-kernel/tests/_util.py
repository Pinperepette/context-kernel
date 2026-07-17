"""Utilita' condivise per i test del plugin. Solo stdlib, zero dipendenze.

I test esercitano gli script col loro contratto REALE (subprocess: JSON su
stdin -> JSON su stdout), non solo le funzioni interne: e' il contratto che
l'harness usa davvero, ed e' li' che vivono i bug (vedi updatedToolOutput
stringa vs dict, 2026-07-15).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(TESTS_DIR)
HOOKS = os.path.join(PLUGIN_ROOT, "hooks")
COMPRESS = os.path.join(HOOKS, "compress.py")
PRETOOL = os.path.join(HOOKS, "pretool_rewrite.py")
SYMPTOM = os.path.join(HOOKS, "symptom_slice.py")
SAVINGS = os.path.join(HOOKS, "savings.py")
AB_VERIFY = os.path.join(HOOKS, "ab_verify.py")
SLICE = os.path.join(PLUGIN_ROOT, "skills", "kernel-slice", "scripts", "slice.py")
MCP_SERVER = os.path.join(PLUGIN_ROOT, "mcp", "server.py")


def run_script(script: str, stdin_text: str, env: dict | None = None,
               args: list[str] | None = None, timeout: int = 30):
    """Esegue uno script col contratto hook: testo su stdin, cattura stdout/stderr."""
    full_env = {**os.environ, **(env or {})}
    # Isolamento: i test producono ELISIONI vere e il campionamento A/B e'
    # attivo di default -> mai scrivere nello stato reale dell'utente.
    if "CK_AB_STATE" not in (env or {}):
        full_env["CK_AB_STATE"] = os.path.join(
            tempfile.gettempdir(), f"ck-ab-test-{os.getpid()}.json")
    # Stesso discorso per il delta dei comandi Bash (CK_CMDS_STATE): file
    # UNICO per invocazione, cosi' il delta scatta solo nei test che
    # passano uno stato condiviso apposta.
    if "CK_CMDS_STATE" not in (env or {}):
        import uuid
        full_env["CK_CMDS_STATE"] = os.path.join(
            tempfile.gettempdir(), f"ck-cmds-test-{uuid.uuid4().hex}.json")
    return subprocess.run(
        [sys.executable, script, *(args or [])],
        input=stdin_text, capture_output=True, text=True,
        timeout=timeout, env=full_env,
    )


def run_hook(script: str, payload, env: dict | None = None):
    """Come run_script ma serializza il payload JSON (o lo passa raw se str)."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return run_script(script, stdin, env=env)


def hook_json(proc) -> dict:
    """Parsa lo stdout di un hook. DEVE essere un singolo oggetto JSON."""
    return json.loads(proc.stdout)


def bash_payload(stdout_text: str, stderr_text: str = "", tool: str = "Bash") -> dict:
    """Payload PostToolUse nella forma reale osservata da Claude Code 2.1.210
    (tool_response e' un dict, NON una stringa)."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"command": "echo test", "description": "test"},
        "tool_response": {
            "stdout": stdout_text,
            "stderr": stderr_text,
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
        },
    }


def read_payload(content_text: str, file_path: str = "/tmp/finto.txt") -> dict:
    """Payload PostToolUse per il tool Read: tool_response ANNIDATO
    {"type": "text", "file": {...}} come osservato nel transcript reale
    (Claude Code 2.1.210, toolUseResult del 2026-07-15)."""
    n_lines = content_text.count("\n") + 1
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": file_path},
        "tool_response": {
            "type": "text",
            "file": {
                "filePath": file_path,
                "content": content_text,
                "numLines": n_lines,
                "startLine": 1,
                "totalLines": n_lines,
            },
        },
    }


def unique_lines(n: int, width_pad: str = "x" * 60) -> list[str]:
    """Righe tutte diverse (niente dedup) e senza spazi finali."""
    return [f"{i:04d} {width_pad}" for i in range(n)]
