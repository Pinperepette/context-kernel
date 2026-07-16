"""Test di savings.py: parsing del CSV e riepilogo."""
from __future__ import annotations

import os
import tempfile
import unittest

import _util


def _run(log_path: str):
    return _util.run_script(_util.SAVINGS, "", env={"CK_LOG": log_path})


class TestSavings(unittest.TestCase):

    def test_report_totals_and_per_tool(self):
        fd, log = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("2026-01-01T00:00:00,Bash,1000,100,900\n")
            fh.write("riga malformata da ignorare\n")
            fh.write("2026-01-01T00:01:00,Read,500,250,250\n")
        try:
            out = _run(log).stdout
        finally:
            os.unlink(log)

        self.assertIn("compressioni:      2", out)   # la malformata non conta
        self.assertIn("1,500", out)                  # before totale
        self.assertIn("1,150", out)                  # risparmiati
        self.assertIn("Bash", out)
        self.assertIn("Read", out)

    def test_missing_log_is_friendly(self):
        out = _run("/percorso/che/non/esiste.csv").stdout
        self.assertIn("Nessun log ancora", out)

    def test_empty_log_is_friendly(self):
        fd, log = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            out = _run(log).stdout
        finally:
            os.unlink(log)
        self.assertIn("Log presente ma vuoto", out)


if __name__ == "__main__":
    unittest.main()
