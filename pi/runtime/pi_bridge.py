#!/usr/bin/env python3
"""Small JSON bridge between the native Pi extension and the tested Python operators.

The bridge intentionally contains no projection logic. It adapts Pi event data to
``compress.py`` and ``pretool_rewrite.py`` so Claude Code and Pi execute the same
T1 implementation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "claude-context-kernel" / "hooks"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rewrite(data: dict) -> dict:
    module = _load("ck_pretool", HOOKS / "pretool_rewrite.py")
    command = str(data.get("command") or "")
    rewritten = module.rewrite(command)
    return {"changed": rewritten != command, "command": rewritten}


def compress(data: dict) -> dict:
    module = _load("ck_compress", HOOKS / "compress.py")
    text = str(data.get("text") or "")
    tool = str(data.get("tool") or "?")
    last_line = text.rstrip().split("\n")[-1] if text.rstrip() else ""
    if not text.strip() or module.FOOTER_MARK in last_line:
        return {"changed": False, "text": text}
    # parita' con il main() Claude: `# ck:raw` nel comando -> output intatto
    command = str((data.get("input") or {}).get("command") or "")
    if module.RAW_MARK and tool.lower() == "bash" and module.RAW_MARK in command:
        return {"changed": False, "text": text}

    before = module.est_tokens(text)
    replacement = None
    if module.DELTA_ENABLED and tool.lower() == "read":
        tool_input = dict(data.get("input") or {})
        if "path" in tool_input and "file_path" not in tool_input:
            tool_input["file_path"] = tool_input["path"]
        payload = {
            "tool_input": tool_input,
            # delta_read only needs a stable session basename. This is not a
            # real transcript path and the Claude canary is never invoked here.
            "transcript_path": f"{data.get('session') or 'pi-session'}.jsonl",
        }
        replacement = module.delta_read(payload, text)

    if replacement is not None:
        projected = replacement
    else:
        if before < module.MIN_TOKENS:
            return {"changed": False, "text": text, "before": before, "after": before}
        projected = module.compress(text)

    after = module.est_tokens(projected)
    if after >= before:
        return {"changed": False, "text": text, "before": before, "after": before}

    saved = 1 - after / before
    footer = f"[context-kernel: {before} -> {after} token, -{saved:.0%}]"
    projected = f"{projected}\n\n{footer}"
    module.log_savings(tool, before, after, str(data.get("session") or "pi")[:8])
    return {
        "changed": True,
        "text": projected,
        "before": before,
        "after": after,
        "footer": footer,
    }


def main() -> int:
    try:
        data = json.load(sys.stdin)
        mode = data.get("mode")
        if mode == "rewrite":
            result = rewrite(data)
        elif mode == "compress":
            result = compress(data)
        else:
            raise ValueError(f"unknown mode: {mode}")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:  # fail-safe: the extension treats this as no-op
        print(json.dumps({"error": str(exc)}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
