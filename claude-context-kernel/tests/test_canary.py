"""Test del canary end-to-end: la compressione risulta APPLICATA nel transcript?

Il canary chiude il buco concettuale del log savings: compress.py logga cio'
che ha CALCOLATO, non cio' che l'harness ha APPLICATO. Il transcript della
sessione registra cio' che e' entrato davvero nel contesto: se il tool_result
di una compressione pending non contiene il footer, l'harness ha ignorato
updatedToolOutput e il canary deve dare l'allarme.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import _util

NOISY = "\n".join(["riga di rumore identica"] * 300)
TID = "toolu_canarytest_0001"


def _transcript_line(tool_use_id: str, text: str) -> str:
    """Riga JSONL come la scrive Claude Code per un tool_result."""
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": [{"type": "text", "text": text}],
        }]},
    }) + "\n"


class CanaryCase(unittest.TestCase):
    """Base: state file + transcript temporanei, env gia' cablato."""

    def setUp(self):
        fd, self.state = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.state)
        fd, self.transcript = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        fd, self.log = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        self.env = {"CK_CANARY_STATE": self.state, "CK_LOG": self.log}

    def tearDown(self):
        for p in (self.state, self.transcript, self.log):
            if os.path.exists(p):
                os.unlink(p)

    def payload(self, stdout_text: str = NOISY, tid: str = TID) -> dict:
        p = _util.bash_payload(stdout_text)
        p["tool_use_id"] = tid
        p["transcript_path"] = self.transcript
        return p

    def state_dict(self) -> dict:
        with open(self.state, encoding="utf-8") as f:
            return json.load(f)

    def seed_pending(self, tid: str = TID, ts_offset: float = 0.0,
                     footer: str | None = None):
        import time
        entry = {"id": tid, "transcript": self.transcript,
                 "ts": time.time() + ts_offset}
        if footer is not None:
            entry["footer"] = footer
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"pending": [entry],
                       "verified": 0, "failed": 0,
                       "last_ok": None, "last_failure": None}, f)


class TestCanaryRecord(CanaryCase):

    def test_compression_records_pending(self):
        proc = _util.run_hook(_util.COMPRESS, self.payload(), env=self.env)
        self.assertIn("updatedToolOutput", proc.stdout)   # ha compresso davvero
        st = self.state_dict()
        self.assertEqual([p["id"] for p in st["pending"]], [TID])
        self.assertEqual(st["pending"][0]["transcript"], self.transcript)

    def test_pending_records_exact_footer(self):
        """Il pending deve portare il footer ESATTO (coi numeri) emesso:
        e' il marcatore che canary_check cerchera' nel transcript."""
        proc = _util.run_hook(_util.COMPRESS, self.payload(), env=self.env)
        upd = _util.hook_json(proc)["hookSpecificOutput"]["updatedToolOutput"]
        st = self.state_dict()
        footer = st["pending"][0]["footer"]
        self.assertRegex(footer, r"^\[context-kernel: \d+ -> \d+ token, -\d+%\]$")
        self.assertIn(footer, upd["stdout"])              # coerente con l'emesso

    def test_subagent_compression_not_recorded(self):
        """Compressione dentro un subagent (agent_id nel payload): il result
        vive in un ALTRO transcript -> pending mai verificabile -> non
        registrare affatto."""
        payload = self.payload()
        payload["agent_id"] = "aqualcosa-123"
        proc = _util.run_hook(_util.COMPRESS, payload, env=self.env)
        self.assertIn("updatedToolOutput", proc.stdout)   # comprime comunque
        self.assertFalse(os.path.exists(self.state))      # ma niente pending

    def test_noop_records_nothing(self):
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        self.assertFalse(os.path.exists(self.state))

    def test_disabled_via_env(self):
        _util.run_hook(_util.COMPRESS, self.payload(),
                       env={**self.env, "CK_CANARY": "0"})
        self.assertFalse(os.path.exists(self.state))


class TestCanaryVerify(CanaryCase):

    def test_footer_in_transcript_means_verified(self):
        self.seed_pending()
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, "output compresso\n\n[context-kernel: 100 -> 10 token, -90%]"))
        proc = _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        self.assertEqual(_util.hook_json(proc), {})       # nessun allarme
        st = self.state_dict()
        self.assertEqual(st["verified"], 1)
        self.assertEqual(st["failed"], 0)
        self.assertEqual(st["pending"], [])
        self.assertIsNotNone(st["last_ok"])

    def test_missing_footer_raises_alert(self):
        """IL caso che il canary esiste per scoprire: hook girato, log
        cresciuto, ma l'output nel transcript e' quello integrale."""
        self.seed_pending()
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, NOISY))          # integrale, no footer
        proc = _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        out = _util.hook_json(proc)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("CANARY", ctx)
        self.assertIn("NON risulta applicata", ctx)
        st = self.state_dict()
        self.assertEqual(st["failed"], 1)
        self.assertEqual(st["pending"], [])
        self.assertIsNotNone(st["last_failure"])

    def test_alert_rides_along_with_compression(self):
        """L'allarme viaggia anche insieme a una compressione nello stesso output."""
        self.seed_pending()
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, NOISY))
        proc = _util.run_hook(_util.COMPRESS, self.payload(tid="toolu_altro"), env=self.env)
        hso = _util.hook_json(proc)["hookSpecificOutput"]
        self.assertIn("updatedToolOutput", hso)
        self.assertIn("CANARY", hso["additionalContext"])

    # --- LA regressione del 2026-07-15 sera: falso "verified" ---------------
    def test_content_citing_footer_is_not_verified(self):
        """Un tool_result INTEGRALE il cui contenuto CITA un footer (doc del
        progetto, log, transcript riletti) NON deve risultare verificato:
        il match va fatto sul footer esatto della compressione pending."""
        self.seed_pending(footer="[context-kernel: 1384 -> 855 token, -38%]")
        citazione = ("il file spiega il formato del footer, es. "
                     "[context-kernel: 1847 -> 1014 token, -45%] a fine output")
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, citazione))
        proc = _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        out = _util.hook_json(proc)
        self.assertIn("CANARY", out["hookSpecificOutput"]["additionalContext"])
        st = self.state_dict()
        self.assertEqual(st["verified"], 0)
        self.assertEqual(st["failed"], 1)

    def test_exact_footer_in_transcript_means_verified(self):
        footer = "[context-kernel: 1384 -> 855 token, -38%]"
        self.seed_pending(footer=footer)
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, f"output compresso\n\n{footer}"))
        proc = _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        self.assertEqual(_util.hook_json(proc), {})
        st = self.state_dict()
        self.assertEqual(st["verified"], 1)
        self.assertEqual(st["failed"], 0)

    # --- LA regressione del 2026-07-18: falso allarme da hint con virgolette
    def test_park_hint_quotes_do_not_break_verification(self):
        """1.15.0: l'hint di parcheggio porta un path tra VIRGOLETTE; nel
        JSONL del transcript diventano \\" e il match esatto footer+hint
        sulla riga grezza fallirebbe -> falso allarme su una compressione
        APPLICATA. Il pending registra il footer NUDO (solo i numeri, mai
        caratteri escapabili) e la verifica passa."""
        varied = "\n".join(
            f"riga ordinaria numero {i} con testo ripetitivo di riempimento"
            for i in range(300))
        proc = _util.run_hook(_util.COMPRESS, self.payload(stdout_text=varied),
                              env=self.env)
        upd = _util.hook_json(proc)["hookSpecificOutput"]["updatedToolOutput"]
        self.assertIn("parcheggiato", upd["stdout"])      # hint presente
        self.assertIn('"', upd["stdout"].split("parcheggiato")[1].split("]")[0])
        st = self.state_dict()
        footer = st["pending"][0]["footer"]
        self.assertRegex(footer, r"^\[context-kernel: \d+ -> \d+ token, -\d+%\]$")
        self.assertNotIn("parcheggiato", footer)          # footer NUDO
        # il transcript registra l'output compresso INTEGRALE, JSON-escapato
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, upd["stdout"]))
        proc2 = _util.run_hook(_util.COMPRESS, self.payload(
            stdout_text="piccolo", tid="toolu_altro"), env=self.env)
        self.assertEqual(_util.hook_json(proc2), {})      # nessun allarme
        st = self.state_dict()
        self.assertEqual(st["verified"], 1)
        self.assertEqual(st["failed"], 0)

    def test_elision_marker_alone_is_not_verified(self):
        """Il marcatore interno di elisione '[context-kernel: elise ...]' non
        e' il footer: senza footer esatto la compressione non risulta applicata."""
        self.seed_pending(footer="[context-kernel: 1384 -> 855 token, -38%]")
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(
                TID, "testa\n[context-kernel: elise 100 righe di rumore "
                     "(~900 token); mantenute 2 righe con segnale]\ncoda"))
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(st["verified"], 0)
        self.assertEqual(st["failed"], 1)

    def test_legacy_pending_without_footer_falls_back_to_mark(self):
        """Pending scritti prima del fix (senza campo footer): fallback al
        prefisso generico, per non condannarli tutti a failed."""
        self.seed_pending()                                # nessun footer
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, "x\n\n[context-kernel: 100 -> 10 token, -90%]"))
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(st["verified"], 1)

    def test_not_yet_in_transcript_stays_pending(self):
        self.seed_pending()
        open(self.transcript, "w").close()                # transcript vuoto
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(len(st["pending"]), 1)
        self.assertEqual(st["verified"], 0)
        self.assertEqual(st["failed"], 0)

    def test_subagent_pending_dropped_after_short_ttl(self):
        """Pending della STESSA sessione mai comparso nel transcript entro il
        TTL breve: e' una compressione dentro un subagent (il suo result vive
        in un altro transcript) -> drop silenzioso, non failed."""
        self.seed_pending(ts_offset=-4000)                # oltre 1h, sotto 24h
        open(self.transcript, "w").close()
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(st["pending"], [])
        self.assertEqual(st["failed"], 0)
        self.assertEqual(st["verified"], 0)

    def test_failure_records_session(self):
        """Ogni fallimento annota la sessione: distingue questa sessione
        dalle headless concorrenti (distiller)."""
        self.seed_pending(footer="[context-kernel: 999 -> 111 token, -89%]")
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(_transcript_line(TID, NOISY))
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(st["failed"], 1)
        self.assertEqual(len(st["failures"]), 1)
        base = os.path.basename(self.transcript)[:8]
        self.assertEqual(st["failures"][0]["session"], base)

    def test_other_session_pending_not_judged_here(self):
        import time
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"pending": [{"id": "toolu_x", "transcript": "/altra/sessione.jsonl",
                                    "ts": time.time()}],
                       "verified": 0, "failed": 0,
                       "last_ok": None, "last_failure": None}, f)
        open(self.transcript, "w").close()
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(len(st["pending"]), 1)           # intatta

    def test_expired_pending_is_dropped(self):
        self.seed_pending(ts_offset=-90_000)              # oltre il TTL di 24h
        open(self.transcript, "w").close()
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(st["pending"], [])
        self.assertEqual(st["failed"], 0)                 # scaduta != fallita

    def test_tool_use_line_is_not_mistaken_for_result(self):
        """La riga assistant con lo stesso id (type: tool_use) non deve
        essere scambiata per il tool_result."""
        self.seed_pending()
        assistant_line = json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": TID,
                "name": "Bash", "input": {"command": "x"},
            }]},
        }) + "\n"
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(assistant_line)                       # solo la tool_use
        _util.run_hook(_util.COMPRESS, self.payload(stdout_text="piccolo"), env=self.env)
        st = self.state_dict()
        self.assertEqual(len(st["pending"]), 1)           # ancora in attesa
        self.assertEqual(st["failed"], 0)


class TestCanaryInSavingsReport(CanaryCase):

    def _seed_log(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("2026-01-01T00:00:00,Bash,1000,100,900\n")

    def test_report_shows_verified(self):
        self._seed_log()
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"pending": [], "verified": 3, "failed": 0,
                       "last_ok": "2026-01-01T00:00:00", "last_failure": None}, f)
        out = _util.run_script(_util.SAVINGS, "", env=self.env).stdout
        self.assertIn("canary: ✓ 3 compressioni verificate", out)

    def test_report_warns_on_failures(self):
        self._seed_log()
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"pending": [], "verified": 1, "failed": 2,
                       "last_ok": None, "last_failure": "2026-01-01T00:00:00"}, f)
        out = _util.run_script(_util.SAVINGS, "", env=self.env).stdout
        self.assertIn("CANARY: ⚠ 2 compressioni NON applicate", out)
        self.assertIn("sovrastimati", out)

    def test_report_silent_without_state(self):
        self._seed_log()
        out = _util.run_script(_util.SAVINGS, "", env=self.env).stdout
        self.assertNotIn("canary", out.lower())

    def test_reset_canary_acks_failures(self):
        """--reset-canary sposta i fallimenti nello storico riconosciuto:
        l'allarme ⚠ si spegne e si riaccende solo su fallimenti NUOVI."""
        self._seed_log()
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"pending": [], "verified": 1, "failed": 2,
                       "failures": [{"ts": "x", "session": "s1"}],
                       "last_ok": None, "last_failure": "2026-01-01T00:00:00"}, f)
        out = _util.run_script(_util.SAVINGS, "", env=self.env,
                               args=["--reset-canary"]).stdout
        self.assertIn("Riconosciuti 2 fallimenti", out)
        report = _util.run_script(_util.SAVINGS, "", env=self.env).stdout
        self.assertNotIn("⚠", report)
        self.assertIn("2 storici riconosciuti", report)


if __name__ == "__main__":
    unittest.main()
