"""Test di ab_autoverify.py: il freno del giudizio A/B automatico
(hook SessionStart). Nessuna chiamata reale a `claude -p`: subprocess.Popen
e' stubbato, si verifica solo la LOGICA del gate (soglia + intervallo + off)."""
from __future__ import annotations

import datetime
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

import _util


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "ck_ab_autoverify", os.path.join(_util.HOOKS, "ab_autoverify.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestABAutoVerifyGate(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.mkdtemp()
        self.mod.AB_STATE = os.path.join(self.tmp, "ab.json")
        self.mod.STAMP = os.path.join(self.tmp, "stamp")
        self.mod.LOG = os.path.join(self.tmp, "log")
        self.mod.MIN_PENDING = 8
        self.mod.EVERY_HOURS = 24
        self.mod.LIMIT = 5
        self.launched = []

        def fake_popen(cmd, *a, **k):        # registra, non lancia nulla
            self.launched.append(cmd)
            return object()
        # subprocess e' un modulo CONDIVISO dal processo pytest: salviamo e
        # ripristiniamo Popen in tearDown, altrimenti il patch globale
        # romperebbe subprocess.run di ogni altro test (contratto hook).
        self._orig_popen = self.mod.subprocess.Popen
        self.mod.subprocess.Popen = fake_popen

    def tearDown(self):
        self.mod.subprocess.Popen = self._orig_popen
        _util.rmtree_force(self.tmp)

    def _write_pending(self, n):
        with open(self.mod.AB_STATE, "w", encoding="utf-8") as f:
            json.dump({"counter": 0, "pending": [{"i": i} for i in range(n)],
                       "ok": 0, "degraded": 0, "last_run": None}, f)

    def _run(self, env=None):
        env = env or {}
        old_stdin, sys.stdin = sys.stdin, io.StringIO("{}")
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            return self.mod.main()
        finally:
            sys.stdin = old_stdin
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.update({k: v})

    def test_below_threshold_does_not_launch(self):
        self._write_pending(3)
        self._run()
        self.assertEqual(self.launched, [])
        self.assertFalse(os.path.exists(self.mod.STAMP))

    def test_threshold_met_launches_and_stamps(self):
        self._write_pending(10)
        self._run()
        self.assertEqual(len(self.launched), 1)
        self.assertIn("ab_verify.py", " ".join(self.launched[0]))
        self.assertIn("--limit", self.launched[0])
        self.assertTrue(os.path.exists(self.mod.STAMP))

    def test_fresh_stamp_throttles(self):
        self._write_pending(10)
        with open(self.mod.STAMP, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat())
        self._run()
        self.assertEqual(self.launched, [])

    def test_off_switch_disables(self):
        self._write_pending(10)
        self._run(env={"CK_AB_AUTO": "0"})
        self.assertEqual(self.launched, [])
        self.assertFalse(os.path.exists(self.mod.STAMP))

    def test_missing_state_does_not_launch(self):
        # nessuno stato A/B (~/.context-kernel-ab.json assente): nel dubbio, fermo
        self._run()
        self.assertEqual(self.launched, [])


if __name__ == "__main__":
    unittest.main()
