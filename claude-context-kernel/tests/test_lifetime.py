"""Context Lifetime Estimator (1.30.0) — il termine MISURATO dello scheduler.

Due livelli, come il resto della suite:
- unita' pure di lifetime.py: la pressione letta dal fault log (recente vs storia),
  neutra al freddo, e la mappa soglia dentro una banda limitata;
- contratto REALE via subprocess: la soglia adattiva CAMBIA se e quando
  compact_advisor.py avvisa, a parita' di occupazione della finestra. Kill-switch
  CK_COMPACT_ADAPT=0 ripristina il 70% fisso.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

import _util

sys.path.insert(0, _util.HOOKS)
import lifetime  # noqa: E402

ADVISOR = os.path.join(_util.HOOKS, "compact_advisor.py")


def _write_log(rows: list[tuple[str, str, str, int]]) -> str:
    fd, path = tempfile.mkstemp(suffix=".log")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for ts, kind, bucket, tok in rows:
            f.write(f"{ts},{kind},{bucket},{tok},sess\n")
    return path


def _ev(n: int, kind: str, bucket: str, tok: int):
    return [(f"2026-07-18T00:00:{i:02d}", kind, bucket, tok) for i in range(n)]


class TestPressure(unittest.TestCase):
    def test_empty_is_neutral(self):
        self.assertEqual(lifetime.recall_pressure([]), 0.5)

    def test_below_min_events_is_neutral(self):
        self.assertEqual(lifetime.recall_pressure(_ev(4, "reread", ".py", 100)),
                         0.5)

    def test_no_baseline_is_neutral(self):
        # meno eventi di RECENT_N: coda = tutto, prior vuoto -> nessuna baseline.
        evs = _ev(10, "reread", ".py", 100)
        self.assertEqual(lifetime.recall_pressure(evs, recent=40), 0.5)

    def test_recent_costlier_raises_pressure(self):
        # prior economico, coda cara -> i drop tornano a mordere -> TIENI (>0.5).
        evs = _ev(10, "reread", ".py", 10) + _ev(5, "reread", ".py", 800)
        p = lifetime.recall_pressure(evs, recent=5)
        self.assertGreater(p, 0.5)

    def test_recent_cheaper_lowers_pressure(self):
        # prior caro, coda economica -> i drop non tornano piu' -> COMPATTA (<0.5).
        evs = _ev(10, "reread", ".py", 800) + _ev(5, "reread", ".py", 10)
        p = lifetime.recall_pressure(evs, recent=5)
        self.assertLess(p, 0.5)

    def test_pressure_is_bounded(self):
        evs = _ev(40, "reread", ".py", 1) + _ev(10, "reread", ".py", 100000)
        self.assertLessEqual(lifetime.recall_pressure(evs, recent=10), 1.0)
        self.assertGreaterEqual(lifetime.recall_pressure(evs, recent=10), 0.0)


class TestThreshold(unittest.TestCase):
    def test_neutral_pressure_is_base(self):
        self.assertAlmostEqual(lifetime.adaptive_threshold(0.70, 0.5), 0.70)

    def test_high_pressure_holds_later(self):
        self.assertGreater(lifetime.adaptive_threshold(0.70, 1.0), 0.70)

    def test_low_pressure_fires_earlier(self):
        self.assertLess(lifetime.adaptive_threshold(0.70, 0.0), 0.70)

    def test_bounded_near_base_and_valid(self):
        # Garanzia di sicurezza: scostamento <= SPAN/2 dalla base, e sempre [0,1].
        for base in (0.05, 0.5, 0.70, 0.9):
            for p in (0.0, 0.5, 1.0):
                thr = lifetime.adaptive_threshold(base, p)
                self.assertLessEqual(abs(thr - base), lifetime.SPAN / 2 + 1e-9)
                self.assertGreaterEqual(thr, 0.0)
                self.assertLessEqual(thr, 1.0)

    def test_neutral_is_base_for_any_base(self):
        # Il fallback grazioso vale per QUALUNQUE base, non solo 0.70.
        for base in (0.05, 0.30, 0.70, 0.95):
            self.assertAlmostEqual(lifetime.adaptive_threshold(base, 0.5), base)


class TestFaultEvents(unittest.TestCase):
    def test_missing_file_is_empty(self):
        self.assertEqual(lifetime.fault_events("/nope/does/not/exist.log"), [])

    def test_parses_and_skips_malformed(self):
        path = _write_log([("2026-01-01T00:00:00", "reread", ".py", 100)])
        with open(path, "a", encoding="utf-8") as f:
            f.write("only,four,fields\n")            # != 5 campi -> skip
            f.write("2026,recmd,bash,notanint,sess\n")  # token non int -> skip
        try:
            evs = lifetime.fault_events(path)
            self.assertEqual(len(evs), 1)
            self.assertEqual(evs[0], ("2026-01-01T00:00:00", "reread", ".py", 100))
        finally:
            os.unlink(path)

    def test_liveness_aggregates_by_bucket(self):
        evs = (_ev(3, "reread", ".py", 100) + _ev(2, "recall", "recall", 40))
        live = lifetime.liveness_by_bucket(evs)
        self.assertEqual(live[".py"], (3, 300))
        self.assertEqual(live["recall"], (2, 80))


class TestAdvisorAdaptive(unittest.TestCase):
    """Contratto reale: a occupazione FISSA (0.62 di una finestra da 100k), la
    soglia adattiva decide se l'avviso scatta. Bassa pressione -> avvisa prima;
    alta pressione -> tiene; kill-switch -> 70% fisso (silenzio)."""

    def _run(self, fault_rows, adapt="1"):
        ctx_fd, ctx = tempfile.mkstemp(suffix=".json")
        os.close(ctx_fd)
        adv_fd, adv = tempfile.mkstemp(suffix=".json")
        os.close(adv_fd)
        os.unlink(adv)                             # deve NON esistere (gate one-shot)
        flog = _write_log(fault_rows)
        sid = "advadapt"
        with open(ctx, "w", encoding="utf-8") as f:
            json.dump({sid: {"context_tokens": 62000, "model": "claude-x"}}, f)
        env = dict(os.environ)
        env.update({
            "CK_CONTEXT_STATE": ctx,
            "CK_ADVISE_STATE": adv,
            "CK_FAULT_LOG": flog,
            "CK_CONTEXT_WINDOW": "100000",
            "CK_COMPACT_ADVISE": "0.70",
            "CK_COMPACT_ADAPT": adapt,
        })
        payload = json.dumps({"transcript_path": f"/t/{sid}.jsonl"})
        try:
            out = subprocess.run(
                [sys.executable, ADVISOR], input=payload, env=env,
                capture_output=True, text=True, cwd=_util.HOOKS)
            return "additionalContext" in out.stdout
        finally:
            for p in (ctx, flog):
                if os.path.exists(p):
                    os.unlink(p)
            if os.path.exists(adv):
                os.unlink(adv)

    # La coda valutata dall'avviso e' RECENT_N=40: il regime recente deve
    # riempirla tutto perche' il segnale sia netto (storia 60 + recenti 40).
    _LOW = _ev(60, "reread", ".py", 800) + _ev(40, "reread", ".py", 5)
    _HIGH = _ev(60, "reread", ".py", 5) + _ev(40, "reread", ".py", 800)

    def test_low_pressure_fires_below_base(self):
        # storia cara, coda economica -> pressione bassa -> soglia ~0.58 ->
        # 0.62 supera -> AVVISA (dove il 70% fisso tacerebbe).
        self.assertTrue(self._run(self._LOW))

    def test_high_pressure_holds(self):
        # storia economica, coda cara -> pressione alta -> soglia ~0.82 ->
        # 0.62 non basta -> TACE (tiene il contesto ancora vivo).
        self.assertFalse(self._run(self._HIGH))

    def test_kill_switch_restores_fixed_70(self):
        # stessa storia a bassa pressione, ma adattamento spento: 70% fisso ->
        # 0.62 < 0.70 -> TACE. Prova che il default e' un vero override.
        self.assertFalse(self._run(self._LOW, adapt="0"))


if __name__ == "__main__":
    unittest.main()
