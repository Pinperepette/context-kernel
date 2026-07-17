"""Test di symptom_slice.py: T2 ambientale su UserPromptSubmit."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import _util

TRACEBACK = """il test fallisce con questo:
Traceback (most recent call last):
  File "app.py", line 4, in main
    return add(1, "x")
TypeError: unsupported operand type(s)"""


def _payload(prompt: str, cwd: str) -> dict:
    return {
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
        "cwd": cwd,
    }


class TestSymptomSlice(unittest.TestCase):

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="ck-symptom-")
        os.makedirs(os.path.join(self.repo, "pkg"))
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("from pkg.calc import add\n\ndef main():\n"
                    "    return add(1, 'x')\n")
        with open(os.path.join(self.repo, "pkg", "calc.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        with open(os.path.join(self.repo, "pkg", "__init__.py"), "w") as f:
            f.write("")
        with open(os.path.join(self.repo, "test_app.py"), "w") as f:
            f.write("import app\n\ndef test_main():\n    assert app.main()\n")
        # fixture minuscola: abbassa la soglia repo-grande per il test
        self.env = {"CK_SYMPTOM_MIN_FILES": "1"}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_traceback_prompt_injects_slice_manifest(self):
        proc = _util.run_hook(_util.SYMPTOM, _payload(TRACEBACK, self.repo),
                              env=self.env)
        self.assertEqual(proc.returncode, 0)
        out = _util.hook_json(proc)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"],
                         "UserPromptSubmit")
        self.assertIn("app.py", ctx)                   # seed dal traceback
        self.assertIn("working set", ctx)
        self.assertIn("kernel-repo-slice", ctx)        # aggancio alla skill

    def test_plain_prompt_is_noop(self):
        proc = _util.run_hook(
            _util.SYMPTOM,
            _payload("aggiungi una pagina di onboarding carina", self.repo),
            env=self.env)
        self.assertEqual(_util.hook_json(proc), {})

    def test_error_word_alone_is_not_a_strong_symptom(self):
        """'c'e' un errore' senza coordinate non deve far partire lo slicer."""
        proc = _util.run_hook(
            _util.SYMPTOM,
            _payload("c'e' un errore da qualche parte nel billing", self.repo),
            env=self.env)
        self.assertEqual(_util.hook_json(proc), {})

    def test_small_repo_is_noop(self):
        proc = _util.run_hook(_util.SYMPTOM, _payload(TRACEBACK, self.repo),
                              env={"CK_SYMPTOM_MIN_FILES": "50"})
        self.assertEqual(_util.hook_json(proc), {})

    def test_slash_command_is_noop(self):
        proc = _util.run_hook(
            _util.SYMPTOM, _payload("/kernel-pipeline " + TRACEBACK, self.repo),
            env=self.env)
        self.assertEqual(_util.hook_json(proc), {})

    def test_manual_pilot_is_noop(self):
        """Se l'utente sta gia' pilotando lo slicer, l'hook non si intromette."""
        proc = _util.run_hook(
            _util.SYMPTOM,
            _payload("lancia repo_slice a mano su questo: " + TRACEBACK,
                     self.repo),
            env=self.env)
        self.assertEqual(_util.hook_json(proc), {})

    def test_disabled_via_env(self):
        proc = _util.run_hook(_util.SYMPTOM, _payload(TRACEBACK, self.repo),
                              env={**self.env, "CK_SYMPTOM": "0"})
        self.assertEqual(_util.hook_json(proc), {})

    def test_missing_cwd_is_noop(self):
        proc = _util.run_hook(
            _util.SYMPTOM, _payload(TRACEBACK, "/percorso/inesistente-xyz"),
            env=self.env)
        self.assertEqual(_util.hook_json(proc), {})

    def test_garbage_stdin_is_noop_exit_zero(self):
        proc = _util.run_hook(_util.SYMPTOM, "niente json", env=self.env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(_util.hook_json(proc), {})

    def test_stdout_is_single_json_object(self):
        proc = _util.run_hook(_util.SYMPTOM, _payload(TRACEBACK, self.repo),
                              env=self.env)
        json.loads(proc.stdout)                        # non deve lanciare


if __name__ == "__main__":
    unittest.main()
