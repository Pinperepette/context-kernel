"""Test di slice.py: correttezza della slice e proprieta' answer-preserving."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest

import _util

FIXTURE = '''\
import math
import os

C = 2

def g(x):
    return math.sqrt(x) + C

def f(x):
    return g(x) * 2

def h(y):
    return os.path.join("a", y)
'''


def _slice(path: str, *symbols: str):
    return subprocess.run(
        [sys.executable, _util.SLICE, path, *symbols],
        capture_output=True, text=True, timeout=30,
    )


class TestSlice(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fd, cls.path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_slice_keeps_transitive_dependencies(self):
        out = _slice(self.path, "f").stdout
        self.assertIn("def f", out)
        self.assertIn("def g", out)            # f usa g
        self.assertIn("C = 2", out)            # g usa C
        self.assertIn("import math", out)      # g usa math

    def test_slice_drops_unreachable_units(self):
        out = _slice(self.path, "f").stdout
        self.assertNotIn("def h", out)         # h non raggiungibile da f
        self.assertNotIn("import os", out)     # os usato solo da h

    def test_slice_of_leaf_drops_everything_else(self):
        out = _slice(self.path, "h").stdout
        self.assertIn("def h", out)
        self.assertIn("import os", out)
        self.assertNotIn("def f", out)
        self.assertNotIn("import math", out)

    def test_slice_is_valid_python(self):
        ast.parse(_slice(self.path, "f").stdout)

    def test_answer_preserving_by_construction(self):
        """La proprieta' centrale: eseguire la slice da' lo STESSO risultato
        del modulo intero, per il simbolo target."""
        full_ns: dict = {}
        exec(compile(FIXTURE, "<full>", "exec"), full_ns)
        sliced_ns: dict = {}
        exec(compile(_slice(self.path, "f").stdout, "<slice>", "exec"), sliced_ns)
        self.assertEqual(sliced_ns["f"](9), full_ns["f"](9))
        self.assertEqual(sliced_ns["f"](16), full_ns["f"](16))

    def test_unknown_symbol_fails_safe_to_whole_file(self):
        out = _slice(self.path, "simbolo_inesistente").stdout
        self.assertIn("def f", out)
        self.assertIn("def h", out)            # file intero: nessuna perdita

    def test_non_python_file_falls_back_to_whole_content(self):
        fd, txt = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("contenuto qualunque, non python")
        try:
            out = _slice(txt, "f").stdout
            self.assertIn("contenuto qualunque", out)
        finally:
            os.unlink(txt)

    def test_missing_args_exits_nonzero_with_usage(self):
        proc = subprocess.run([sys.executable, _util.SLICE],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("uso:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
