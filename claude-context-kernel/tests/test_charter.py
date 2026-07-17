"""Test di charter.py (persistenza della carta T3) e charter_guard.py
(la carta come invariante attivo sugli Edit/Write)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import _util

CARTA = """# carta del task
Q: add esplode sui tipi misti

## vincoli
1. [contratto]    add(a, b) somma numeri; TypeError sui misti  (pkg/calc.py:1)
2. [comportamento] main() ritorna un int  (app.py:3)
3. [invariante]   il pool non e' mai None dopo setup  (pkg/calc.py:2)

## percorso del sintomo
TypeError nasce in pkg/calc.py, raggiunto da app.main
"""


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ck-charter-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "pkg"))
        self.charter_state = os.path.join(self.tmp, "charter.json")
        self.guard_state = os.path.join(self.tmp, "guard.json")
        self.env = {"CK_CHARTER_STATE": self.charter_state,
                    "CK_GUARD_STATE": self.guard_state}
        _util.run_script(_util.CHARTER, CARTA, env=self.env,
                         args=["save", "--repo", self.repo])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _edit_payload(self, fpath: str, session: str = "s1") -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "session_id": session,
            "cwd": self.repo,
            "tool_input": {"file_path": fpath,
                           "old_string": "a", "new_string": "b"},
        }


class TestCharter(_Base):

    def test_save_indexes_citations(self):
        st = json.load(open(self.charter_state))
        rec = st[os.path.normpath(os.path.abspath(self.repo))]
        self.assertIn("pkg/calc.py", rec["files"])
        self.assertEqual(len(rec["files"]["pkg/calc.py"]), 2)
        self.assertIn("app.py", rec["files"])

    def test_get_returns_charter(self):
        proc = _util.run_script(_util.CHARTER, "", env=self.env,
                                args=["get", "--repo", self.repo])
        self.assertIn("carta del task", proc.stdout)
        self.assertIn("TypeError sui misti", proc.stdout)

    def test_clear_removes(self):
        _util.run_script(_util.CHARTER, "", env=self.env,
                         args=["clear", "--repo", self.repo])
        proc = _util.run_script(_util.CHARTER, "", env=self.env,
                                args=["get", "--repo", self.repo])
        self.assertNotIn("TypeError", proc.stdout)

    def test_vincolo_senza_citazione_non_indicizzato(self):
        carta = "# carta del task\n\n## vincoli\n1. [contratto] senza cita\n"
        repo2 = os.path.join(self.tmp, "repo2")
        os.makedirs(repo2)
        proc = _util.run_script(_util.CHARTER, carta, env=self.env,
                                args=["save", "--repo", repo2])
        self.assertIn("0 vincoli indicizzati", proc.stdout)


class TestCharterGuard(_Base):

    def test_edit_of_cited_file_injects_constraints(self):
        fpath = os.path.join(self.repo, "pkg", "calc.py")
        out = _util.hook_json(_util.run_hook(
            _util.GUARD, self._edit_payload(fpath), env=self.env))
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("CARTA DEL TASK", ctx)
        self.assertIn("TypeError sui misti", ctx)
        self.assertIn("pool non e' mai None", ctx)     # entrambi i vincoli
        self.assertNotIn("ritorna un int", ctx)        # vincolo di ALTRO file

    def test_same_file_deduped_within_ttl(self):
        fpath = os.path.join(self.repo, "pkg", "calc.py")
        _util.run_hook(_util.GUARD, self._edit_payload(fpath), env=self.env)
        out = _util.hook_json(_util.run_hook(
            _util.GUARD, self._edit_payload(fpath), env=self.env))
        self.assertEqual(out, {})

    def test_resaved_charter_speaks_again(self):
        fpath = os.path.join(self.repo, "pkg", "calc.py")
        _util.run_hook(_util.GUARD, self._edit_payload(fpath), env=self.env)
        _util.run_script(_util.CHARTER, CARTA + "\n4. [x] nuovo  (pkg/calc.py:9)\n",
                         env=self.env, args=["save", "--repo", self.repo])
        out = _util.hook_json(_util.run_hook(
            _util.GUARD, self._edit_payload(fpath), env=self.env))
        self.assertIn("additionalContext", out.get("hookSpecificOutput", {}))

    def test_uncited_file_is_noop(self):
        fpath = os.path.join(self.repo, "altro.py")
        out = _util.hook_json(_util.run_hook(
            _util.GUARD, self._edit_payload(fpath), env=self.env))
        self.assertEqual(out, {})

    def test_write_tool_also_guarded(self):
        payload = self._edit_payload(os.path.join(self.repo, "app.py"))
        payload["tool_name"] = "Write"
        payload["tool_input"] = {"file_path": payload["tool_input"]["file_path"],
                                 "content": "x"}
        out = _util.hook_json(_util.run_hook(_util.GUARD, payload, env=self.env))
        self.assertIn("ritorna un int",
                      out["hookSpecificOutput"]["additionalContext"])

    def test_no_charter_is_noop(self):
        env = {"CK_CHARTER_STATE": os.path.join(self.tmp, "vuoto.json"),
               "CK_GUARD_STATE": self.guard_state}
        fpath = os.path.join(self.repo, "pkg", "calc.py")
        out = _util.hook_json(_util.run_hook(
            _util.GUARD, self._edit_payload(fpath), env=env))
        self.assertEqual(out, {})

    def test_disabled_via_env(self):
        fpath = os.path.join(self.repo, "pkg", "calc.py")
        out = _util.hook_json(_util.run_hook(
            _util.GUARD, self._edit_payload(fpath),
            env={**self.env, "CK_GUARD": "0"}))
        self.assertEqual(out, {})

    def test_garbage_stdin_is_noop_exit_zero(self):
        proc = _util.run_hook(_util.GUARD, "niente json", env=self.env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(_util.hook_json(proc), {})


if __name__ == "__main__":
    unittest.main()
