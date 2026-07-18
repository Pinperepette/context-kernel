"""window.py: la fonte UNICA della finestra di contesto (1.18.0).

Prima la stessa domanda aveva tre risposte (advisor, budget auto, scala
adattiva): qui si testa il risolutore condiviso — ordine di fiducia
env -> pattern -> stima prudente, fonte sempre dichiarata."""
from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock

import _util

_spec = importlib.util.spec_from_file_location(
    "ck_window", os.path.join(_util.HOOKS, "window.py"))
window = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(window)


class TestResolveWindow(unittest.TestCase):

    def test_env_wins_over_everything(self):
        with mock.patch.dict(os.environ, {"CK_CONTEXT_WINDOW": "616000"}):
            self.assertEqual(window.resolve_window("model-[1m]", 500_000),
                             (616_000, "env"))

    def test_known_pattern_in_model_name(self):
        with mock.patch.dict(os.environ, {"CK_CONTEXT_WINDOW": ""}):
            win, src = window.resolve_window("claude-x-[1m]", 100_000)
        self.assertEqual((win, src), (1_000_000, "pattern [1m]"))

    def test_estimate_floor_and_growth(self):
        with mock.patch.dict(os.environ, {"CK_CONTEXT_WINDOW": ""}):
            self.assertEqual(window.resolve_window("ignoto", 0)[0], 200_000)
            self.assertEqual(window.resolve_window(None, 0)[0], 200_000)
            win, src = window.resolve_window("ignoto", 400_000)
        self.assertEqual(win, 510_000)                    # 400k*1.15 + 50k
        self.assertEqual(src, "stima")

    def test_estimate_saturates_below_relative_thresholds(self):
        """La proprieta' che rende la stima SICURA per le soglie relative
        (advisor 0.70, rampa 60-90%): used/win non supera mai ~0.87."""
        with mock.patch.dict(os.environ, {"CK_CONTEXT_WINDOW": ""}):
            for used in (200_000, 500_000, 2_000_000):
                win, _ = window.resolve_window("ignoto", used)
                self.assertLess(used / win, 0.88)

    def test_env_invalid_falls_through(self):
        with mock.patch.dict(os.environ, {"CK_CONTEXT_WINDOW": "abc"}):
            self.assertEqual(window.resolve_window("x", 0)[1], "stima")


if __name__ == "__main__":
    unittest.main()
