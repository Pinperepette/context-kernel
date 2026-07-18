"""Parcheggio degli output effimeri elisi + recall mirato + compact advisor.

Il page fault delle Read esiste perche' il file e' su disco; per Bash/MCP
l'inversa non c'era: l'elisione perdeva il mezzo per sempre. Il parcheggio
la rende reversibile (recall --grep/--lines, deterministico), e il footer
DICHIARA la via. L'advisor: una riga una-tantum quando la finestra supera
la soglia (il /compact manuale costa meno dell'auto-compact al pieno).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import unittest

import _util

ADVISOR = os.path.join(_util.PLUGIN_ROOT, "hooks", "compact_advisor.py")
RECALL = os.path.join(_util.PLUGIN_ROOT, "hooks", "recall.py")


def _noisy_with_needle(n: int = 300) -> str:
    lines = [f"riga ordinaria numero {i} con testo ripetitivo di riempimento"
             for i in range(n)]
    lines[140] = "riga speciale AGO-NEL-PAGLIAIO 0142 senza segnale forte"
    return "\n".join(lines)


class TestPark(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ck-park-")
        self.park = os.path.join(self.dir, "park.json")
        self.env = {"CK_LOG_OFF": "1", "CK_CANARY": "0",
                    "CK_PARK_STATE": self.park,
                    "CK_READS_STATE": os.path.join(self.dir, "reads.json")}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _compress(self, text: str, env: dict | None = None):
        return _util.run_hook(_util.COMPRESS, _util.bash_payload(text),
                              env={**self.env, **(env or {})})

    def _park_key(self, stdout: str) -> str:
        # nello stdout del hook le virgolette sono JSON-escapate: aggancia
        # la chiave alla forma "KEY --grep PATTERN" del suggerimento
        m = re.search(r"([0-9a-f]{10}) --grep PATTERN", stdout)
        self.assertIsNotNone(m, f"footer senza hint di parcheggio: {stdout[-400:]}")
        return m.group(1)

    def test_elided_bash_output_is_parked_with_declared_recall(self):
        proc = self._compress(_noisy_with_needle())
        key = self._park_key(proc.stdout)
        self.assertIn("parcheggiato", proc.stdout)
        with open(self.park, encoding="utf-8") as f:
            st = json.load(f)
        self.assertIn(key, st)
        self.assertEqual(st[key]["tool"], "Bash")

    def test_recall_grep_recovers_elided_line(self):
        """La riga senza segnale forte viene ELISA dal contesto ma il grep
        sul parcheggio la recupera: il fault costa solo cio' che chiedi."""
        proc = self._compress(_noisy_with_needle())
        self.assertNotIn("AGO-NEL-PAGLIAIO", proc.stdout)   # davvero elisa
        key = self._park_key(proc.stdout)
        rec = _util.run_script(RECALL, "", args=[key, "--grep",
                                                 "AGO-NEL-PAGLIAIO"],
                               env=self.env)
        self.assertEqual(rec.returncode, 0, rec.stderr)
        self.assertIn("AGO-NEL-PAGLIAIO 0142", rec.stdout)
        self.assertIn("141\t", rec.stdout)                  # numerata (1-based)

    def test_recall_lines_range(self):
        proc = self._compress(_noisy_with_needle())
        key = self._park_key(proc.stdout)
        rec = _util.run_script(RECALL, "", args=[key, "--lines", "10-12"],
                               env=self.env)
        self.assertIn("riga ordinaria numero 9 ", rec.stdout)
        self.assertIn("riga ordinaria numero 11 ", rec.stdout)
        self.assertNotIn("numero 12 ", rec.stdout)

    def test_small_output_not_parked(self):
        self._compress("poche righe\nniente elisione")
        self.assertFalse(os.path.exists(self.park))

    def test_kill_switch(self):
        proc = self._compress(_noisy_with_needle(), env={"CK_PARK": "0"})
        self.assertNotIn("parcheggiato", proc.stdout)
        self.assertFalse(os.path.exists(self.park))

    def test_recall_unknown_key_exits_2(self):
        rec = _util.run_script(RECALL, "", args=["deadbeef00"], env=self.env)
        self.assertEqual(rec.returncode, 2)
        self.assertIn("assente o scaduta", rec.stderr)


class TestCompactAdvisor(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ck-advise-")
        self.ctx = os.path.join(self.dir, "context.json")
        self.env = {"CK_CONTEXT_STATE": self.ctx,
                    "CK_ADVISE_STATE": os.path.join(self.dir, "advised.json")}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _tap(self, used: int):
        with open(self.ctx, "w", encoding="utf-8") as f:
            json.dump({"abcd1234": {"model": "test-model",
                                    "context_tokens": used,
                                    "ts": time.time()}}, f)

    def _run(self, env: dict | None = None):
        payload = {"tool_name": "Bash",
                   "transcript_path": "/x/abcd1234-ef.jsonl",
                   "tool_input": {"command": "ls"}}
        return _util.hook_json(_util.run_script(
            ADVISOR, json.dumps(payload), env={**self.env, **(env or {})}))

    def test_advises_once_above_threshold(self):
        self._tap(190_000)                     # finestra stimata ~268k -> ~71%
        out = self._run()
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("/compact MANUALE", ctx)
        self.assertIn("una-tantum", ctx)
        self.assertEqual(self._run(), {})      # seconda volta: silenzio

    def test_silent_below_threshold(self):
        self._tap(100_000)
        self.assertEqual(self._run(), {})

    def test_disabled_via_env(self):
        self._tap(190_000)
        self.assertEqual(self._run(env={"CK_COMPACT_ADVISE": "0"}), {})

    def test_subagent_never_advised(self):
        self._tap(190_000)
        payload = {"tool_name": "Bash", "agent_id": "a1b2",
                   "transcript_path": "/x/abcd1234-ef.jsonl"}
        out = _util.hook_json(_util.run_script(
            ADVISOR, json.dumps(payload), env=self.env))
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
