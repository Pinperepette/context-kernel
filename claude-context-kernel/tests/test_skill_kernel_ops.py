"""kernel-ops — superficie operativa a linguaggio naturale (gemello dei /ck-*).

Guardie contro il rot: la skill deve restare model-invocable (disable-model-
invocation false) e ogni script che instrada deve esistere davvero sotto hooks/.
Una skill che punta a uno script rinominato fallisce solo al primo uso reale.
"""
from __future__ import annotations

import os
import re
import unittest

import _util

SKILL = os.path.join(_util.PLUGIN_ROOT, "skills", "kernel-ops", "SKILL.md")

# Gli script che la skill deve saper instradare (i mattoni dei /ck-*).
ROUTED_SCRIPTS = [
    "savings.py", "ab_verify.py", "doctor.py",
    "recall.py", "charter.py", "smoke.py", "revealed.py",
]


def _read():
    with open(SKILL, encoding="utf-8") as fh:
        return fh.read()


class TestKernelOps(unittest.TestCase):
    def test_skill_exists(self):
        self.assertTrue(os.path.isfile(SKILL), "manca skills/kernel-ops/SKILL.md")

    def test_frontmatter(self):
        text = _read()
        self.assertTrue(text.startswith("---\n"), "frontmatter mancante")
        end = text.find("\n---", 4)
        self.assertNotEqual(end, -1, "frontmatter non chiuso")
        front = text[4:end]
        self.assertRegex(front, r"(?m)^name:\s*kernel-ops\b", "name errato/mancante")
        self.assertRegex(front, r"(?m)^description:\s*\S", "description mancante")
        # Deve essere invocabile dal modello (il punto: niente slash command).
        self.assertRegex(
            front, r"(?m)^disable-model-invocation:\s*false\b",
            "la skill deve restare model-invocable (disable-model-invocation: false)")

    def test_routes_only_to_real_scripts(self):
        text = _read()
        for script in ROUTED_SCRIPTS:
            self.assertIn(
                script, text, f"la skill non instrada verso {script}")
            self.assertTrue(
                os.path.isfile(os.path.join(_util.HOOKS, script)),
                f"la skill cita {script} ma non esiste sotto hooks/")

    def test_no_bare_script_reference_is_dangling(self):
        # Ogni <nome>.py citato nel corpo deve esistere sotto hooks/.
        text = _read()
        for script in set(re.findall(r"\b([a-z_]+\.py)\b", text)):
            self.assertTrue(
                os.path.isfile(os.path.join(_util.HOOKS, script)),
                f"riferimento penzolante nel corpo: {script}")


if __name__ == "__main__":
    unittest.main()
