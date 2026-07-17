"""Test di contratto del bridge Pi (pi/runtime/pi_bridge.py).

Il bridge riusa gli interni di compress.py/pretool_rewrite.py invece del
contratto hook: un refactor di quei moduli lo romperebbe in silenzio (il
bridge e' fail-safe e degrada a no-op). Questi test tengono il contratto
sotto la NOSTRA suite, senza bisogno di node/Pi.

Saltati quando pi/ non c'e' (es. esecuzione dalla cache del plugin Claude,
che impacchetta solo claude-context-kernel/).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import _util

BRIDGE = os.path.join(os.path.dirname(_util.PLUGIN_ROOT),
                      "pi", "runtime", "pi_bridge.py")


def _call(payload: dict, env: dict | None = None) -> dict:
    proc = _util.run_script(BRIDGE, json.dumps(payload), env={
        "CK_LOG_OFF": "1",
        "CK_CANARY": "0",
        "CK_READS_STATE": os.path.join(
            tempfile.gettempdir(), f"ck-pi-bridge-test-{os.getpid()}.json"),
        "CK_MIN_TOKENS": "20",
        **(env or {}),
    })
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@unittest.skipUnless(os.path.exists(BRIDGE), "pi/ non presente (cache plugin)")
class TestPiBridge(unittest.TestCase):

    def test_rewrite_reuses_quiet_rules(self):
        out = _call({"mode": "rewrite", "command": "npm install | head"})
        self.assertTrue(out["changed"])
        self.assertIn("--no-fund", out["command"])

    def test_compress_preserves_signal(self):
        lines = [f"ordinaria {i} {'x' * 40}" for i in range(150)]
        lines[80] = "ERROR: database unavailable"
        out = _call({"mode": "compress", "tool": "bash",
                     "text": "\n".join(lines), "session": "pytest"})
        self.assertTrue(out["changed"])
        self.assertIn("ERROR: database unavailable", out["text"])
        self.assertIn("[context-kernel:", out["text"])
        self.assertLess(out["after"], out["before"])

    def test_compress_respects_ck_raw(self):
        lines = [f"ordinaria {i} {'x' * 40}" for i in range(150)]
        out = _call({"mode": "compress", "tool": "bash",
                     "text": "\n".join(lines), "session": "pytest",
                     "input": {"command": "pytest -x  # ck:raw"}})
        self.assertFalse(out["changed"])
        self.assertNotIn("[context-kernel:", out["text"])

    def test_unknown_mode_fails_safe(self):
        out = _call({"mode": "boh"})
        self.assertIn("error", out)
