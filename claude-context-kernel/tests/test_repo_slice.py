"""Test di repo_slice.py (T2): grafo import, seed dal sintomo, slice, page-fault."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _util

REPO_SLICE = os.path.join(_util.PLUGIN_ROOT, "skills", "kernel-repo-slice",
                          "scripts", "repo_slice.py")

FIXTURE = {
    "app/__init__.py": "",
    "app/util.py": "def helper():\n    return 42\n",
    "app/db.py": (
        "from app.util import helper\n\n"
        "def connect(addr):\n"
        "    raise ConnectionError('connection refused by upstream')\n"
    ),
    "app/api.py": "from app import db\n\ndef handle():\n    return db.connect('x')\n",
    "app/unrelated.py": "def other():\n    return 'niente a che fare'\n",
    "tests/test_db.py": "from app.db import connect\n\ndef test_connect():\n    connect('x')\n",
    "app/loader.py": "def load():\n    return 1\n",
    "tests/test_loader.py": "import subprocess  # carica loader.py via subprocess, zero import\n",
    "tests/test_dyn.py": 'import subprocess\nSCRIPT = "loader.py"\n',
    "app/two.py": "A = 1\n",
    "lib/two.py": "B = 2\n",
    "tests/test_two_ref.py": 'X = "two.py"\n',
    "tests/test_unrelated.py": "from app.unrelated import other\n",
    "web/index.js": "import { fmt } from './helper.js';\nconsole.log(fmt(1));\n",
    "web/helper.js": "export function fmt(x) { return x; }\n",
    "web/orphan.js": "export const nulla = true;\n",
    "node_modules/junk/index.js": "module.exports = 'spazzatura';\n",
    "dist/bundle.js": "var x=1;\n",
}

PY_SYMPTOM = '''Traceback (most recent call last):
  File "app/api.py", line 4, in handle
    return db.connect('x')
  File "app/db.py", line 4, in connect
    raise ConnectionError('connection refused by upstream')
ConnectionError: connection refused by upstream'''


def _run(root: str, *extra: str, env: dict | None = None):
    """Cache DISATTIVA di default: i test non devono toccare ne' dipendere
    dalla cache reale (i test di cache la riattivano con path temporaneo)."""
    full = {**os.environ, "CK_SLICE_CACHE": "0", **(env or {})}
    return subprocess.run([sys.executable, REPO_SLICE, root, *extra],
                          capture_output=True, text=True, timeout=60, env=full)


class RepoSliceCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ck-repo-")
        for rel, content in FIXTURE.items():
            path = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)


class TestSeedsAndSlice(RepoSliceCase):

    def test_python_traceback_slice(self):
        out = _run(self.root, "--symptom", PY_SYMPTOM).stdout
        self.assertIn("app/db.py — seed", out)         # dal frame
        self.assertIn("app/api.py — seed", out)        # anche lui nei frame
        self.assertIn("app/util.py — dipendenza", out) # db importa util
        self.assertIn("tests/test_db.py — test correlato", out)
        self.assertNotIn("app/unrelated.py", out)
        self.assertNotIn("tests/test_unrelated.py", out)
        self.assertNotIn("web/", out)                  # altro linguaggio, non toccato
        self.assertNotIn("node_modules", out.split("## fuori slice")[0])

    def test_importer_found_without_its_frame(self):
        """Solo il frame di db.py: api.py (caller) va trovato come importatore."""
        symptom = 'File "app/db.py", line 4, in connect'
        out = _run(self.root, "--symptom", symptom).stdout
        self.assertIn("app/db.py — seed", out)
        self.assertIn("app/api.py — importatore", out)

    def test_error_literal_greps_raise_site(self):
        """Niente path nel sintomo: il letterale quotato trova il raise site."""
        out = _run(self.root, "--symptom",
                   "il servizio muore con 'connection refused by upstream'").stdout
        self.assertIn('app/db.py  <- contiene il letterale', out)
        self.assertIn("app/util.py — dipendenza", out)

    def test_js_stack_frame_slice(self):
        out = _run(self.root, "--symptom",
                   "TypeError: fmt is not a function\n    at main (web/index.js:2:13)").stdout
        self.assertIn("web/index.js — seed", out)
        self.assertIn("web/helper.js — dipendenza", out)
        self.assertNotIn("web/orphan.js", out)
        self.assertNotIn("app/", out)

    def test_explicit_seed(self):
        out = _run(self.root, "--seed", "app/db.py").stdout
        self.assertIn("app/db.py  <- seed esplicito", out)

    def test_dynamic_test_reference_found(self):
        """Test che caricano il sorgente SENZA import statico (importlib da
        path, subprocess): trovati per convenzione di nome o per citazione
        del basename tra virgolette."""
        out = _run(self.root, "--seed", "app/loader.py").stdout
        self.assertIn("tests/test_loader.py — test correlato (usa app/loader.py)", out)
        self.assertIn("tests/test_dyn.py — test correlato (usa app/loader.py)", out)

    def test_ambiguous_ref_basename_not_guessed(self):
        """Basename citato ma ambiguo (piu' sorgenti omonimi): nessun arco."""
        out = _run(self.root, "--seed", "app/two.py").stdout
        self.assertNotIn("test_two_ref", out)

    def test_excluded_dirs_never_scanned(self):
        out = _run(self.root, "--symptom", PY_SYMPTOM, "--json").stdout
        data = json.loads(out)
        paths = {f["path"] for f in data["files"]}
        self.assertFalse(any("node_modules" in p or p.startswith("dist/")
                             for p in paths))
        # e non contano nemmeno tra gli scansionati
        self.assertEqual(data["scanned"], 16)          # 18 fixture - 2 esclusi

    def test_json_structure(self):
        data = json.loads(_run(self.root, "--symptom", PY_SYMPTOM, "--json").stdout)
        self.assertEqual(data["kept"], len(data["files"]))
        self.assertGreater(data["excluded"], 0)
        roles = {f["role"] for f in data["files"]}
        self.assertLessEqual(roles, {"seed", "dipendenza", "importatore", "test"})
        seed_paths = {s["path"] for s in data["seeds"]}
        self.assertIn("app/db.py", seed_paths)

    def test_manifest_declares_page_fault(self):
        out = _run(self.root, "--symptom", PY_SYMPTOM).stdout
        self.assertIn("page-fault", out)
        self.assertIn("prior, non un divieto", out)


class TestFailSafe(RepoSliceCase):

    def test_no_seed_is_explicit_not_silent(self):
        proc = _run(self.root, "--symptom", "boh, qualcosa non va")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("nessun seed riconosciuto", proc.stderr)
        self.assertIn("nessuna proiezione applicata", proc.stderr)

    def test_missing_repo_exits_nonzero(self):
        proc = _run("/percorso/inesistente", "--symptom", "x")
        self.assertEqual(proc.returncode, 2)

    def test_absolute_frame_path_matched_by_longest_suffix(self):
        """Frame con path ASSOLUTO fuori dal root e basename ambiguo: il
        suffisso lungo (dir/file) deve agganciare il file giusto, senza
        scendere al basename (regressione pandas: generic.py x3)."""
        extra = os.path.join(self.root, "web", "db.py")
        with open(extra, "w", encoding="utf-8") as f:
            f.write("pass\n")
        try:
            symptom = f'File "/altro/prefisso/inesistente/app/db.py", line 4, in connect'
            out = _run(self.root, "--symptom", symptom).stdout
            self.assertIn("app/db.py  <- frame stack trace", out)
            self.assertNotIn("web/db.py  <-", out)
        finally:
            os.unlink(extra)

    def test_deps_depth_caps_closure(self):
        """--deps-depth limita la chiusura delle dipendenze: con 1 hop
        util.py (2 hop da api.py) resta fuori; senza limite entra."""
        full = _run(self.root, "--seed", "app/api.py").stdout
        self.assertIn("app/util.py — dipendenza", full)
        capped = _run(self.root, "--seed", "app/api.py", "--deps-depth", "1").stdout
        self.assertIn("app/db.py — dipendenza", capped)
        self.assertNotIn("app/util.py — dipendenza", capped)

    def test_package_root_prefixed_imports_resolved(self):
        """Root = directory del package stesso (root=pandas/): gli import col
        prefisso del package (from mypkg.core.x import y) vanno risolti."""
        base = tempfile.mkdtemp(prefix="ck-pkgroot-")
        root = os.path.join(base, "mypkg")
        try:
            fixture = {
                "__init__.py": "",
                "core/__init__.py": "",
                "core/frame.py": "from mypkg.core.generic import NDFrame\n",
                "core/generic.py": "NDFrame = object\n",
            }
            for rel, content in fixture.items():
                p = os.path.join(root, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
            out = _run(root, "--seed", "core/frame.py").stdout
            self.assertIn("core/generic.py — dipendenza", out)
        finally:
            shutil.rmtree(base)

    def test_inroot_absolute_path_relativized(self):
        """Path assoluto DENTRO il root con gemello nei test (app/db.py vs
        tests/app/db.py): la relativizzazione deve vincere sull'ambiguita'
        del suffisso (regressione pandas: io/excel/__init__.py)."""
        twin = os.path.join(self.root, "tests", "app", "db.py")
        os.makedirs(os.path.dirname(twin), exist_ok=True)
        with open(twin, "w", encoding="utf-8") as f:
            f.write("pass\n")
        try:
            abs_frame = os.path.join(self.root, "app", "db.py")
            out = _run(self.root, "--symptom", f'File "{abs_frame}", line 4').stdout
            self.assertIn("app/db.py  <- frame stack trace", out)
        finally:
            shutil.rmtree(os.path.join(self.root, "tests", "app"))

    def test_budget_picks_richest_fitting_config(self):
        """--budget e' in TOKEN stimati (size/4): config piu' ricca che
        rientra; sotto, scala; se nemmeno il minimo (seed+test) rientra,
        INSODDISFACIBILE — ma i seed non si tagliano mai."""
        out = _run(self.root, "--seed", "app/api.py", "--budget", "100000").stdout
        self.assertIn("scelta config deps=full", out)
        self.assertIn("token", out)
        # slice piena ~49 token: budget 30 forza la discesa, util (2 hop) esce
        out = _run(self.root, "--seed", "app/api.py", "--budget", "30").stdout
        self.assertIn("app/api.py — seed", out)
        self.assertNotIn("app/util.py", out)
        out = _run(self.root, "--symptom", PY_SYMPTOM, "--budget", "3").stdout
        self.assertIn("INSODDISFACIBILE", out)
        self.assertIn("app/db.py — seed", out)

    def test_budget_note_in_json(self):
        out = _run(self.root, "--seed", "app/api.py", "--budget", "100000", "--json").stdout
        data = json.loads(out)
        self.assertIn("budget", data)
        self.assertIn("deps=full", data["budget"])
        self.assertIn("token", data["budget"])

    def test_t2b_symbol_slice_on_unsatisfiable_budget(self):
        """Budget insoddisfacibile a livello di file -> T2b: metodo di classe
        estratto per righe (sed), funzione top-level via backward slice."""
        base = tempfile.mkdtemp(prefix="ck-t2b-")
        try:
            filler = "\n".join(f"# filler {i}" for i in range(200))
            big = (f"{filler}\n"
                   "class Motore:\n"
                   "    def avvia(self):\n"
                   "        raise RuntimeError('motore ingolfato irreparabilmente')\n"
                   f"{filler}\n"
                   "def utilita():\n"
                   "    return 1\n")
            files = {"pkg/__init__.py": "", "pkg/big.py": big,
                     "pkg/caller.py": "from pkg import big\n"}
            for rel, content in files.items():
                p = os.path.join(base, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
            # riga dentro Motore.avvia = 200 filler + class(201) + def(202) + raise(203)
            symptom = (f'Traceback (most recent call last):\n'
                       f'  File "{base}/pkg/caller.py", line 1, in <module>\n'
                       f'  File "{base}/pkg/big.py", line 203, in avvia\n'
                       f"RuntimeError: motore ingolfato irreparabilmente")
            out = _run(base, "--symptom", symptom, "--budget", "60").stdout
            self.assertIn("## T2b", out)
            self.assertIn("Motore.avvia (righe 202-203)", out)
            self.assertIn("sed -n '202,203p'", out)
            self.assertIn("RIENTRA", out)
            # JSON: struttura t2b presente
            out = _run(base, "--symptom", symptom, "--budget", "60", "--json").stdout
            data = json.loads(out)
            self.assertTrue(data["t2b"]["fits"])
            self.assertEqual(data["t2b"]["slices"][0]["esito"] in ("metodi", "slice",
                             "file intero (nessun simbolo dal sintomo)"), True)
        finally:
            shutil.rmtree(base)

    def test_budget_auto_from_context_state(self):
        """--budget auto: finestra - occupato dallo stato del hook T1;
        senza stato, fallback 30k dichiarato."""
        import time as _t
        fd, state = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(state, "w", encoding="utf-8") as f:
                json.dump({"abc12345": {"model": "claude-test-1",
                                        "context_tokens": 100_000,
                                        "ts": _t.time()}}, f)
            env = {**os.environ, "CK_CONTEXT_STATE": state}
            proc = subprocess.run(
                [sys.executable, REPO_SLICE, self.root,
                 "--seed", "app/api.py", "--budget", "auto"],
                capture_output=True, text=True, timeout=60, env=env)
            out = proc.stdout
            # finestra stimata 200k, in uso 100k, headroom 100k -> 40%
            self.assertIn("auto: sessione abc12345", out)
            self.assertIn("headroom ~100k -> budget 40k", out)
        finally:
            os.unlink(state)
        env = {**os.environ, "CK_CONTEXT_STATE": "/percorso/inesistente.json"}
        proc = subprocess.run(
            [sys.executable, REPO_SLICE, self.root,
             "--seed", "app/api.py", "--budget", "auto"],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertIn("fallback 30k", proc.stdout)

    def test_manifest_cache_hit_and_invalidation(self):
        """Operator hash-skip: run identico -> manifest riusato; file
        toccato -> ricalcolo; CK_SLICE_CACHE=0 -> mai cache."""
        fd, cpath = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(cpath)
        env = {"CK_SLICE_CACHE": "1", "CK_SLICE_CACHE_PATH": cpath}
        try:
            out1 = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
            self.assertNotIn("manifest riusato", out1)
            self.assertIn("operatore: T2@", out1)
            out2 = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
            self.assertIn("manifest riusato", out2)
            self.assertIn(out1.strip().split("\n")[2], out2)  # stesso manifest
            os.utime(os.path.join(self.root, "app", "db.py"))  # tocca un file
            out3 = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
            self.assertNotIn("manifest riusato", out3)
        finally:
            if os.path.exists(cpath):
                os.unlink(cpath)

    def test_cache_json_hit_stays_valid_json(self):
        fd, cpath = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(cpath)
        env = {"CK_SLICE_CACHE": "1", "CK_SLICE_CACHE_PATH": cpath}
        try:
            _run(self.root, "--symptom", PY_SYMPTOM, "--json", env=env)
            out = _run(self.root, "--symptom", PY_SYMPTOM, "--json", env=env).stdout
            data = json.loads(out)                         # nessuna riga extra
            self.assertIn("operator", data)
        finally:
            if os.path.exists(cpath):
                os.unlink(cpath)

    def test_ambiguous_basename_not_guessed(self):
        """Due file con lo stesso basename: nessun match arbitrario."""
        extra = os.path.join(self.root, "web", "db.py")
        with open(extra, "w", encoding="utf-8") as f:
            f.write("pass\n")
        try:
            out = _run(self.root, "--symptom", 'File "db.py", line 1').stdout
            self.assertIn("(nessuno)", out)
        finally:
            os.unlink(extra)


if __name__ == "__main__":
    unittest.main()
