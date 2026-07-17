"""Test di revealed.py (T5, rilevanza rivelata): dal transcript ricava
file della slice mai aperti, file aperti fuori slice, page fault
post-elisione col loro costo in token."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import _util

MANIFEST = "\n".join([
    "# kernel repo slice — manifest",
    "operatore: T2@test",
    "repo: /repo",
    "sorgenti scansionati: 100  |  slice: 3 file (-97%)",
    "",
    "## seed (dal sintomo)",
    "- app.py  <- citato nel sintomo",
    "",
    "## file della slice (per rilevanza)",
    "- app.py — seed",
    "- pkg/calc.py — dipendenza a 1 hop (via app.py)",
    "- test_app.py — test correlato (usa app.py)",
    "",
    "## fuori slice (modello page-fault)",
    "97 sorgenti esclusi dal grafo degli import.",
])


def _tool_use(tid: str, name: str, finput: dict) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": finput}]}}


def _tool_result(tid: str, text: str) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid,
         "content": [{"type": "text", "text": text}]}]}}


class TestRevealed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ck-revealed-")
        self.transcript = os.path.join(self.tmp, "sessione.jsonl")
        lines = [
            {"type": "user", "message": {"content": [
                {"type": "text",
                 "text": "[context-kernel] Sintomo rilevato\n" + MANIFEST}]}},
            _tool_use("t1", "Read", {"file_path": "/repo/app.py"}),
            _tool_result("t1", "x" * 100 +
                         "\n[context-kernel: elise righe 46-90: 40 righe]"
                         "\n[context-kernel: 500 -> 100 token, -80%] "
                         "[copia ELISA: per l'integrale rileggi questo "
                         "stesso file]"),
            _tool_use("t2", "Read", {"file_path": "/repo/app.py"}),
            _tool_result("t2", "y" * 400),
            _tool_use("t3", "Read", {"file_path": "/repo/config/extra.py"}),
            _tool_result("t3", "z" * 100),
        ]
        with open(self.transcript, "w") as f:
            for l in lines:
                f.write(json.dumps(l) + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        return _util.run_script(_util.REVEALED, "", args=list(args))

    def test_report_covers_all_signals(self):
        out = self._run(self.transcript).stdout
        self.assertIn("manifest T2: 3 file", out)
        self.assertIn("aperti dalla slice: 1/3", out)
        self.assertIn("pkg/calc.py", out)              # mai aperto
        self.assertIn("test_app.py", out)
        self.assertIn("FUORI slice", out)
        self.assertIn("config/extra.py", out)          # seed perso
        self.assertIn("page fault post-elisione: 1", out)
        self.assertIn("suggerimento", out)

    def test_fault_cost_measured_from_reread(self):
        r = json.loads(self._run(self.transcript, "--json").stdout)[0]
        self.assertEqual(len(r["faults"]), 1)
        self.assertEqual(r["faults"][0]["file"], "/repo/app.py")
        self.assertAlmostEqual(r["faults"][0]["tokens"], 100,
                               delta=5)                # ~400 char / 4

    def test_directory_argument(self):
        out = self._run(self.tmp).stdout
        self.assertIn("rilevanza rivelata", out)

    def test_transcript_without_slice(self):
        empty = os.path.join(self.tmp, "vuota.jsonl")
        with open(empty, "w") as f:
            f.write(json.dumps(_tool_use("a", "Read",
                                         {"file_path": "/x.py"})) + "\n")
        out = self._run(empty).stdout
        self.assertIn("nessun manifest T2", out)

    def test_no_transcript_exits_nonzero(self):
        proc = self._run(os.path.join(self.tmp, "inesistente.jsonl"))
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
