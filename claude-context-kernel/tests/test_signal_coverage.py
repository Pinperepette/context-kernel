"""Copertura delle regex SIGNAL e CODE_SIGNAL per linguaggio e formato.

Nato dall'audit del 2026-07-17 (innescato dalla segnalazione PHP/Joomla):
la classe di bug era "keyword non conosciuta -> segnale eliso", e valeva
per molti linguaggi oltre il PHP. Questi test sono la tabella dell'audit:
se una keyword regredisce, il test dice QUALE riga e QUALE linguaggio.

Unit-test diretti sulle regex (via importlib): il contratto hook end-to-end
e' gia' coperto da test_compress.py.
"""
from __future__ import annotations

import importlib.util
import os
import unittest

import _util


def _load_compress():
    spec = importlib.util.spec_from_file_location("ck_compress_sig", _util.COMPRESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CK = _load_compress()

STRUCTURAL = [
    ("Python", "def calcola(x):"),
    ("Python", "async def fetch(url):"),
    ("Python", "from collections import defaultdict"),
    ("JS", "async function fetchAll() {"),
    ("JS", "export const config = {};"),
    ("TS", "type Handler = (e: Event) => void"),
    ("Go", "type Config struct {"),
    ("Go", "func main() {"),
    ("Rust", "mod tests;"),
    ("Rust", "async fn fetch_all() -> Result<()> {"),
    ("Rust", "use std::collections::HashMap;"),
    ("PHP", "use Joomla\\CMS\\Factory;"),
    ("PHP", "namespace Acme\\Site\\Model;"),
    ("PHP", "require_once JPATH_BASE . '/includes/defines.php';"),
    ("PHP", "final class ArticleModel extends BaseModel"),
    ("PHP", "abstract class BaseDatabaseModel"),
    ("Ruby", "require 'json'"),
    ("Ruby", "require_relative 'helper'"),
    ("C", "#include <vector>"),
    ("C", "#define MAX_SIZE 1024"),
    ("C", "typedef struct node Node;"),
    ("C", "static void helper(void) {"),
    ("C++", "template <typename T>"),
    ("C++", "using namespace std;"),
    ("C#", "using System.Collections.Generic;"),
    ("Kotlin", "fun main(args: Array<String>) {"),
    ("Kotlin", "data class User(val id: Int)"),
    ("Kotlin", "override fun toString() = \"u\""),
    ("Kotlin", "sealed class Result"),
    ("Scala", "object Main extends App {"),
    ("Scala", "case class Point(x: Int, y: Int)"),
    ("Swift", "extension String {"),
    ("Swift", "protocol Drawable {"),
    ("Shell", "source ./env.sh"),
]

BODY_NOISE = [
    "    return valore",
    "    except Exception:",
    "        pass",
    "$db->setQuery($query);",
    "console.log(risultato);",
    "    end",
    "        x += 1",
]

LOG_SIGNAL = [
    "Deprecated: strlen(): Passing null to parameter #1",
    "PHP Notice:  Undefined index: id",
    "Strict Standards: Only variables should be passed by reference",
    "Segmentation fault (core dumped)",
    "Killed",
    "Connection timed out after 30000 ms",
    "npm ERR! code ETIMEDOUT",
    "bash: foo: command not found",
    "rm: /x: No such file or directory",
    "CONFLICT (content): Merge conflict in app.py",
    "Aborted (core dumped)",
    "unable to resolve host github.com",
    "Invalid argument",
    "unexpected token '}' at line 3",
    "OOM killer invoked for process 1234",
    "write error: Broken pipe",
]

LOG_NOISE = [
    "default configuration loaded",          # \bfault non deve prendere "default"
    "the skilled worker finished the job",   # \bkilled\b non deve prendere "skilled"
    "meeting room 12 booked",                # \boom\b non deve prendere "room"
    "Compiling module 12 of 40",
    "Copied 14 files to build/",
    "riga ordinaria 42 xxxxxxxxxxxxxxxx",
]


class TestCodeSignalCoverage(unittest.TestCase):

    def test_structural_lines_match(self):
        for lang, line in STRUCTURAL:
            with self.subTest(lang=lang, line=line):
                self.assertIsNotNone(
                    CK.CODE_SIGNAL.match(line),
                    f"[{lang}] riga strutturale NON riconosciuta: {line!r}")

    def test_body_lines_do_not_match(self):
        for line in BODY_NOISE:
            with self.subTest(line=line):
                self.assertIsNone(
                    CK.CODE_SIGNAL.match(line),
                    f"riga di corpo scambiata per struttura: {line!r}")


class TestLogSignalCoverage(unittest.TestCase):

    def test_error_lines_match(self):
        for line in LOG_SIGNAL:
            with self.subTest(line=line):
                self.assertIsNotNone(
                    CK.SIGNAL.search(line),
                    f"riga d'errore NON riconosciuta: {line!r}")

    def test_ordinary_lines_do_not_match(self):
        for line in LOG_NOISE:
            with self.subTest(line=line):
                self.assertIsNone(
                    CK.SIGNAL.search(line),
                    f"riga ordinaria scambiata per segnale: {line!r}")


if __name__ == "__main__":
    unittest.main()
