"""La superficie di slash command /ck-* deve restare ben formata e non marcire.

I file in commands/ sono prompt scopribili che wrappano gli script in hooks/.
Il rischio e' il rot: un comando che cita uno script rinominato/rimosso, o un
frontmatter rotto, fallisce solo al primo uso reale. Qui lo blocchiamo prima:
ogni comando ha un frontmatter YAML con description, e ogni riferimento
${CLAUDE_PLUGIN_ROOT}/hooks/<x>.py punta a uno script che esiste davvero.
"""
from __future__ import annotations

import os
import re
import unittest

import _util

COMMANDS_DIR = os.path.join(_util.PLUGIN_ROOT, "commands")

# I comandi minimi che la superficie deve sempre offrire.
EXPECTED = {
    "ck-status", "ck-savings", "ck-verify", "ck-recall",
    "ck-charter", "ck-smoke", "ck-doctor", "ck-tune",
}

_HOOK_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([A-Za-z0-9_]+\.py)")


def _command_files():
    return [f for f in os.listdir(COMMANDS_DIR) if f.endswith(".md")]


def _read(name: str) -> str:
    with open(os.path.join(COMMANDS_DIR, name), encoding="utf-8") as fh:
        return fh.read()


class TestCommands(unittest.TestCase):
    def test_dir_exists(self):
        self.assertTrue(os.path.isdir(COMMANDS_DIR), "manca commands/")

    def test_expected_commands_present(self):
        have = {f[:-3] for f in _command_files()}
        missing = EXPECTED - have
        self.assertFalse(missing, f"comandi mancanti: {sorted(missing)}")

    def test_frontmatter_has_description(self):
        for name in _command_files():
            text = _read(name)
            self.assertTrue(
                text.startswith("---\n"), f"{name}: frontmatter mancante")
            end = text.find("\n---", 4)
            self.assertNotEqual(end, -1, f"{name}: frontmatter non chiuso")
            front = text[4:end]
            self.assertRegex(
                front, r"(?m)^description:\s*\S",
                f"{name}: description mancante o vuota")

    def test_hook_references_exist(self):
        for name in _command_files():
            for script in _HOOK_REF.findall(_read(name)):
                path = os.path.join(_util.HOOKS, script)
                self.assertTrue(
                    os.path.isfile(path),
                    f"{name} cita hooks/{script} che non esiste")

    def test_at_least_one_hook_reference(self):
        # Ogni comando deve wrappare almeno uno script reale (non prosa vuota).
        for name in _command_files():
            self.assertTrue(
                _HOOK_REF.search(_read(name)),
                f"{name}: nessun riferimento a uno script hooks/")

    def test_installer_ships_commands(self):
        # L'install manuale deve copiare la superficie in ~/.claude/commands/,
        # altrimenti chi non usa la via plugin non riceve i /ck-*.
        installer = os.path.join(_util.PLUGIN_ROOT, "install.sh")
        with open(installer, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn(".claude/commands", body,
                      "install.sh non copia i comandi in ~/.claude/commands")
        self.assertIn("commands/*.md", body,
                      "install.sh non itera sui file dei comandi")


if __name__ == "__main__":
    unittest.main()
