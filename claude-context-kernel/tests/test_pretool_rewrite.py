"""Test di pretool_rewrite.py: regole quiet-flag e contratto PreToolUse."""
from __future__ import annotations

import unittest

import _util


def _payload(cmd: str, tool: str = "Bash") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": cmd, "description": "test"},
    }


def _rewritten(proc) -> str:
    out = _util.hook_json(proc)
    return out["hookSpecificOutput"]["updatedInput"]["command"]


class TestRewriteRules(unittest.TestCase):

    def test_repo_slice_gets_auto_budget(self):
        """repo_slice.py senza --budget: il rewriter inietta '--budget auto'
        (operatore costo ambientale); con --budget esplicito non tocca."""
        payload = _payload("python3 skills/kernel-repo-slice/scripts/repo_slice.py . --symptom x")
        proc = _util.run_hook(_util.PRETOOL, payload)
        out = _util.hook_json(proc)
        cmd = out["hookSpecificOutput"]["updatedInput"]["command"]
        self.assertTrue(cmd.endswith("--budget auto"))
        payload = _payload("python3 x/repo_slice.py . --budget 5000")
        proc = _util.run_hook(_util.PRETOOL, payload)
        self.assertEqual(_util.hook_json(proc), {})

    def test_flags_injected_before_pipe_not_at_end(self):
        """Regressione: con una pipe i flag vanno al segmento giusto,
        non in coda all'intero comando (head --budget = rotto)."""
        payload = _payload("python3 x/repo_slice.py . --symptom x | head -4")
        proc = _util.run_hook(_util.PRETOOL, payload)
        cmd = _util.hook_json(proc)["hookSpecificOutput"]["updatedInput"]["command"]
        self.assertIn("--budget auto | head -4", cmd)
        self.assertFalse(cmd.endswith("--budget auto"))

    def test_flags_injected_before_fd_redirect(self):
        """`2>/dev/null`: il flag va prima della redirezione, senza
        lasciare il numero di fd orfano come argomento."""
        payload = _payload("python3 x/repo_slice.py . --symptom x 2>/dev/null > out.txt")
        proc = _util.run_hook(_util.PRETOOL, payload)
        cmd = _util.hook_json(proc)["hookSpecificOutput"]["updatedInput"]["command"]
        self.assertIn("--symptom x --budget auto 2>/dev/null", cmd)

    def test_pip_install_gets_quiet(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("pip3 install requests"))
        self.assertEqual(_rewritten(proc), "pip3 install requests -q")

    def test_npm_install_gets_all_flags(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("npm install"))
        self.assertEqual(_rewritten(proc),
                         "npm install --no-fund --no-audit --no-progress")

    def test_npm_existing_flag_not_duplicated(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("npm install --no-fund"))
        cmd = _rewritten(proc)
        self.assertEqual(cmd.count("--no-fund"), 1)
        self.assertIn("--no-audit", cmd)
        self.assertIn("--no-progress", cmd)

    def test_pnpm_add_gets_silent_reporter(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("pnpm add lodash"))
        self.assertEqual(_rewritten(proc), "pnpm add lodash --reporter=silent")

    def test_yarn_add_gets_non_interactive(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("yarn add left-pad"))
        self.assertEqual(_rewritten(proc), "yarn add left-pad --non-interactive")

    def test_updated_input_preserves_other_fields(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("pip install x"))
        out = _util.hook_json(proc)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["updatedInput"]["description"], "test")


class TestCommandPositionAnchor(unittest.TestCase):

    def test_repo_slice_as_argument_is_noop(self):
        """Regressione (bug reale): repo_slice.py citato come ARGOMENTO
        (grep/cat/wc) riceveva --budget auto e rompeva il comando."""
        for cmd in (
            "grep -n -e 'def ' skills/kernel-repo-slice/scripts/repo_slice.py",
            "command grep -e 'x' /a/b/repo_slice.py | head -5",
            "cat repo_slice.py",
            "wc -l scripts/repo_slice.py",
        ):
            proc = _util.run_hook(_util.PRETOOL, _payload(cmd))
            self.assertEqual(_util.hook_json(proc), {}, cmd)

    def test_repo_slice_direct_execution_matches(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("./repo_slice.py . --symptom x"))
        self.assertTrue(_rewritten(proc).endswith("--budget auto"))

    def test_repo_slice_after_chain_matches(self):
        proc = _util.run_hook(
            _util.PRETOOL,
            _payload("cd /repo && python3 scripts/repo_slice.py . --symptom y"))
        self.assertTrue(_rewritten(proc).endswith("--budget auto"))

    def test_quoted_install_command_is_noop(self):
        """Un comando citato in una stringa non e' in posizione di comando."""
        for cmd in ('git commit -m "npm install fix"',
                    "echo 'pip install requests'"):
            proc = _util.run_hook(_util.PRETOOL, _payload(cmd))
            self.assertEqual(_util.hook_json(proc), {}, cmd)

    def test_env_prefix_still_matches(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("CI=1 npm install"))
        self.assertTrue(_rewritten(proc).endswith(
            "--no-fund --no-audit --no-progress"))

class TestNoopCases(unittest.TestCase):

    def test_unrelated_command_is_noop(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("ls -la"))
        self.assertEqual(_util.hook_json(proc), {})

    def test_already_quiet_is_noop(self):
        """Idempotenza: se il flag c'e' gia', nessuna riscrittura."""
        proc = _util.run_hook(_util.PRETOOL, _payload("pip3 install x -q"))
        self.assertEqual(_util.hook_json(proc), {})

    def test_non_bash_tool_is_noop(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("pip install x", tool="Edit"))
        self.assertEqual(_util.hook_json(proc), {})

    def test_empty_command_is_noop(self):
        proc = _util.run_hook(_util.PRETOOL, _payload(""))
        self.assertEqual(_util.hook_json(proc), {})

    def test_disabled_via_env(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("pip install x"),
                              env={"CK_PRETOOL": "0"})
        self.assertEqual(_util.hook_json(proc), {})

    def test_garbage_stdin_is_noop_exit_zero(self):
        proc = _util.run_hook(_util.PRETOOL, "niente json")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(_util.hook_json(proc), {})


class TestPermissionDecision(unittest.TestCase):

    def test_no_auto_allow_by_default(self):
        """Di default NON forza l'approvazione: l'utente deve vedere il prompt."""
        proc = _util.run_hook(_util.PRETOOL, _payload("pip install x"))
        hso = _util.hook_json(proc)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hso)

    def test_auto_allow_only_with_explicit_env(self):
        proc = _util.run_hook(_util.PRETOOL, _payload("pip install x"),
                              env={"CK_PRETOOL_ALLOW": "1"})
        hso = _util.hook_json(proc)["hookSpecificOutput"]
        self.assertEqual(hso.get("permissionDecision"), "allow")


class TestHeredocAndBoundaries(unittest.TestCase):
    """LA regressione del 2026-07-18: il salvataggio della carta T3 via
    heredoc conteneva la citazione '(.../repo_slice.py:258)' nel CORPO —
    l'ancora `(` di CMD_POS (pensata per le subshell) matchava, e lo splice
    con rest.lstrip() mangiava il newline fondendo due vincoli (con
    '--budget auto' iniettato nel DOCUMENTO). Successo DUE volte (1.11.0 e
    1.17): il corpo di un heredoc e' dati, mai comandi."""

    def test_heredoc_is_never_rewritten(self):
        cmd = ("python3 hooks/charter.py save --repo . << 'CARTA'\n"
               "3. FQCN mai indovinato (skills/scripts/repo_slice.py:258)\n"
               "4. I tassi appresi solo relax (hooks/compress.py:727)\n"
               "CARTA")
        proc = _util.run_hook(_util.PRETOOL, _payload(cmd))
        self.assertEqual(_util.hook_json(proc), {})       # intatto, nessun output

    def test_newline_boundary_preserved_on_rewrite(self):
        cmd = "pip install requests\necho fatto"
        proc = _util.run_hook(_util.PRETOOL, _payload(cmd))
        new = _rewritten(proc)
        self.assertIn("pip install requests -q\necho fatto", new)
        self.assertNotIn("-q echo", new)                  # niente fusione


if __name__ == "__main__":
    unittest.main()
