# The bridge contract — port context-kernel to your harness in ~100 lines

The Pi port proved a claim of the formalism: **operators travel between
harnesses**. All projection logic lives in the tested Python operators
(`claude-context-kernel/hooks/`); a harness port is a thin adapter that maps
your agent's events to a small JSON contract. `pi/runtime/pi_bridge.py` is the
reference implementation (~100 lines, zero duplicated logic) and
`pi/extensions/context-kernel.js` is the host side for Pi.

## The contract

One process invocation per event. JSON object on **stdin**, one JSON object on
**stdout**, exit code 0 always.

### mode: "rewrite"  (before running a shell command)

Wire it to your *pre-tool* event for shell commands.

```json
{"mode": "rewrite", "command": "npm install"}
→ {"changed": true, "command": "npm install --no-fund --no-audit ..."}
```

- `changed: false` → run the command untouched.
- Quiet-flag rules live in `pretool_rewrite.py`; the bridge adds nothing.

### mode: "compress"  (after a tool produced output)

Wire it to your *post-tool* event.

```json
{"mode": "compress", "tool": "bash", "text": "<raw output>",
 "session": "<stable session id>", "input": {"command": "<the command>"}}
→ {"changed": true, "text": "<normalized output ending with the
    [context-kernel: N -> M token, -P%] footer>"}
```

- `session` scopes the re-read delta state: an unchanged re-read becomes a
  3-line marker, a changed file becomes a diff. Use a stable id per
  conversation.
- Parity guarantees the host must inherit for free (they are in the
  operators, not in your adapter): signal lines survive, every elision leaves
  a visible marker, `# ck:raw` in a shell command exempts that output, an
  already-footered text is never re-normalized (double-run guard).

## The three rules of a port

1. **No projection logic in the adapter.** If your port needs to trim, dedup
   or summarize anything itself, it is wrong — send it through the contract.
2. **Fail-safe means no-op.** Any bridge error returns
   `{"error": "..."}` with exit 0 and the host treats it as "use the
   original text". The plugin must never break the harness.
3. **Re-implement the canary on your native surface.** A savings log proves
   the operator *computed* a replacement, not that your harness *applied* it.
   Pi verifies application on its native tool-result event; do the equivalent
   on yours, or state that you have no canary.

## Keeping the port honest

The bridge couples to operator internals (`rewrite()`, `normalize()`,
`delta_read()`, `FOOTER_MARK`, `RAW_MARK`). That risk is frozen in a contract
test **on the Python side** — `claude-context-kernel/tests/test_pi_bridge.py`
runs the bridge as a subprocess and fails if a refactor breaks it. A new port
should add the same kind of test: your adapter, invoked for real, against the
operators of this repository.

What does *not* travel through this contract: the ambient hooks (T1 on every
tool call, ambient T2 on tracebacks, the T3 guard, compact/resume snapshots)
depend on your harness having hook points for those events. Where they do not
exist, the port has less coverage — say so in your README rather than
approximating it in the adapter. The `kernel_slice` / `kernel_repo_slice` MCP
tools need no port at all: any MCP-speaking agent can call them directly.
