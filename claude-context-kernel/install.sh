#!/usr/bin/env bash
# install.sh — installazione MANUALE di context-kernel (tutti i progetti).
#
# ⚠ VIA PREFERITA (Claude Code >= 2.x): il PLUGIN NATIVO —
#     /plugin marketplace add pinperepette/context-kernel
#     /plugin install context-kernel
#   (oppure marketplace add <path locale del repo>). Gestisce da solo
#   hook/skill/agent/MCP, enable/disable/uninstall, niente path fissi.
#   NON usare entrambe le vie insieme: gli hook si sommerebbero (c'e' una
#   guardia anti doppia-compressione, ma e' spreco).
# Questo script resta per: Codex e ambienti senza il sistema plugin.
#
# Cosa fa (idempotente, rilanciabile quando vuoi — es. se evolver
# sovrascrive ~/.claude/settings.json):
#   1. hooks Pre/PostToolUse  -> ~/.claude/settings.json   (scope utente)
#   2. server MCP kernel_slice -> `claude mcp add --scope user` (~/.claude.json)
#   3. skill kernel-slice / kernel-verify -> ~/.claude/skills/
#
# NB: ~/.claude/settings.local.json NON viene letto da Claude Code
# (settings.local.json esiste solo a livello progetto): non usarlo.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="$HOME/.claude/settings.json"

echo "== context-kernel installer =="
echo "plugin dir: $PLUGIN_DIR"

# --- 1. hooks in ~/.claude/settings.json (merge non distruttivo) ----------
python3 - "$PLUGIN_DIR" "$SETTINGS" <<'PY'
import json, shutil, sys

plugin, path = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        cfg = json.load(f)
except FileNotFoundError:
    cfg = {}

shutil.copy(path, path + ".bak-context-kernel")  # backup dell'ultimo stato

hooks = cfg.setdefault("hooks", {})

def ensure(event, matcher, command, status, timeout):
    blocks = hooks.setdefault(event, [])
    for b in blocks:  # gia' presente? (idempotenza per path del comando)
        for h in b.get("hooks", []):
            if command in h.get("command", ""):
                h.update(command=command, timeout=timeout, statusMessage=status)
                b["matcher"] = matcher
                return "aggiornato"
    blocks.append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command,
                   "timeout": timeout, "statusMessage": status}],
    })
    return "aggiunto"

r1 = ensure("PreToolUse", "Bash",
            f"python3 {plugin}/hooks/pretool_rewrite.py",
            "context-kernel: rewrite", 10)
r2 = ensure("PostToolUse", "Bash|Grep|Read|Glob|WebFetch",
            f"python3 {plugin}/hooks/compress.py",
            "context-kernel: compress", 10)

with open(path, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  hooks: PreToolUse {r1}, PostToolUse {r2} -> {path}")
PY

# --- 2. server MCP (scope user = tutti i progetti) -------------------------
if command -v claude >/dev/null 2>&1; then
    claude mcp remove --scope user context-kernel >/dev/null 2>&1 || true
    claude mcp add --scope user context-kernel -- python3 "$PLUGIN_DIR/mcp/server.py" \
        && echo "  mcp: context-kernel registrato (scope user)"
else
    echo "  mcp: CLI 'claude' non trovata — registra a mano:"
    echo "       claude mcp add --scope user context-kernel -- python3 $PLUGIN_DIR/mcp/server.py"
fi

# --- 3. skill globali -------------------------------------------------------
mkdir -p "$HOME/.claude/skills"
for s in kernel-slice kernel-verify kernel-repo-slice kernel-invariants kernel-pipeline; do
    if [ -d "$PLUGIN_DIR/skills/$s" ]; then
        rm -rf "$HOME/.claude/skills/$s"
        cp -R "$PLUGIN_DIR/skills/$s" "$HOME/.claude/skills/$s"
        echo "  skill: $s -> ~/.claude/skills/$s"
    fi
done

# --- 4. agent globali (stadi della pipeline nei workflow multi-agente) ------
mkdir -p "$HOME/.claude/agents"
for a in "$PLUGIN_DIR"/agents/*.md; do
    [ -e "$a" ] || continue
    cp "$a" "$HOME/.claude/agents/$(basename "$a")"
    echo "  agent: $(basename "$a" .md) -> ~/.claude/agents/"
done

echo "== fatto. Riavvia Claude Code (o nuova sessione) per caricare hook/skill/agent =="
