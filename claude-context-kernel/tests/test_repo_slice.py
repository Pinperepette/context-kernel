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
    full = {**os.environ, "CK_SLICE_CACHE": "0", "CK_PRIORS": "0",
            "PYTHONIOENCODING": "utf-8", **(env or {})}
    return subprocess.run([sys.executable, REPO_SLICE, root, *extra],
                          capture_output=True, text=True, timeout=60, env=full,
                          encoding="utf-8", errors="replace")


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


PHP_FIXTURE = {
    "src/Service/Mailer.php": (
        "<?php\nnamespace App\\Service;\n\n"
        "use App\\Transport\\Smtp;\n"
        "use App\\Util\\{Logger, Clock};\n\n"
        "class Mailer {\n"
        "    public function send() {\n"
        "        throw new \\RuntimeException('mail backend down');\n"
        "    }\n"
        "}\n"
    ),
    "src/Transport/Smtp.php": "<?php\nnamespace App\\Transport;\n\nclass Smtp {}\n",
    "src/Util/Logger.php": "<?php\nnamespace App\\Util;\n\nclass Logger {}\n",
    "src/Util/Clock.php": "<?php\nnamespace App\\Util;\n\nclass Clock {}\n",
    "src/Controller/MailController.php": (
        "<?php\nnamespace App\\Controller;\n\n"
        "use App\\Service\\Mailer;\n\n"
        "class MailController {\n"
        "    public function invia() { (new Mailer())->send(); }\n"
        "}\n"
    ),
    "src/legacy.php": "<?php\nrequire_once __DIR__ . '/Service/Mailer.php';\n",
    "src/Orphan.php": "<?php\nnamespace App;\n\nclass Orphan {}\n",
    "tests/MailerTest.php": (
        "<?php\nuse App\\Service\\Mailer;\n\nclass MailerTest {}\n"
    ),
}

PHP_SYMPTOM = (
    "PHP Fatal error:  Uncaught RuntimeException: mail backend down in "
    "/var/www/html/src/Service/Mailer.php:9\n"
    "Stack trace:\n"
    "#0 /var/www/html/src/Controller/MailController.php(7): "
    "App\\Service\\Mailer->send()\n"
    "#1 {main}\n"
    "  thrown in /var/www/html/src/Service/Mailer.php on line 9"
)


class TestPhpSlice(unittest.TestCase):
    """T2 su repository PHP: seed dai frame PHP, archi use/require, test."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ck-php-")
        for rel, content in PHP_FIXTURE.items():
            path = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_php_fatal_error_slice(self):
        """Frame PHP assoluti (fuori root) -> seed per suffisso; use -> archi."""
        out = _run(self.root, "--symptom", PHP_SYMPTOM).stdout
        self.assertIn("src/Service/Mailer.php — seed", out)
        self.assertIn("src/Controller/MailController.php — seed", out)
        self.assertIn("src/Transport/Smtp.php — dipendenza", out)   # use singolo
        self.assertIn("src/Util/Logger.php — dipendenza", out)      # use di gruppo
        self.assertIn("src/Util/Clock.php — dipendenza", out)       # use di gruppo
        self.assertIn("tests/MailerTest.php — test correlato", out)
        self.assertNotIn("src/Orphan.php", out.split("## fuori slice")[0])

    def test_php_require_edge(self):
        """require_once __DIR__.'/...' -> arco verso il file incluso."""
        out = _run(self.root, "--seed", "src/legacy.php").stdout
        self.assertIn("src/legacy.php  <- seed esplicito", out)
        self.assertIn("src/Service/Mailer.php — dipendenza", out)

    def test_php_on_line_frame_seeds(self):
        """La sola forma 'in FILE.php on line N' basta come seed."""
        out = _run(self.root, "--symptom",
                   "errore in src/Transport/Smtp.php on line 3").stdout
        self.assertIn("src/Transport/Smtp.php — seed", out)


GO_FIXTURE = {
    "go.mod": "module example.com/app\n\ngo 1.22\n",
    "main.go": (
        "package main\n\n"
        "import (\n"
        "\t\"fmt\"\n"
        "\t\"example.com/app/api\"\n"
        "\t\"example.com/app/db\"\n"
        ")\n\n"
        "func main() {\n"
        "\tfmt.Println(api.Serve(db.Query()))\n"
        "}\n"),
    "api/api.go": (
        "package api\n\n"
        "import handlers \"example.com/app/db\"\n\n"
        "func Serve(q string) string { return handlers.Query() + q }\n"),
    "db/db.go": (
        "package db\n\n"
        "func Query() string { panic(\"connection refused\") }\n"),
    "db/util.go": (
        "package db\n\n"
        "func helper() int { return 1 }\n"),
    "db/db_test.go": (
        "package db\n\n"
        "import \"testing\"\n\n"
        "func TestQuery(t *testing.T) { Query() }\n"),
    "extra/orphan.go": (
        "package extra\n\n"
        "import \"os\"\n\n"
        "func Unused() string { return os.Getenv(\"X\") }\n"),
}

GO_SYMPTOM = (
    "panic: runtime error: connection refused\n\n"
    "goroutine 1 [running]:\n"
    "example.com/app/db.Query(...)\n"
    "\t/home/ci/work/app/db/db.go:3 +0x1b\n"
    "main.main()\n"
    "\t/home/ci/work/app/main.go:10 +0x2f\n"
)


class TestGoSlice(unittest.TestCase):
    """T2 su repository Go: seed dai frame del goroutine dump, archi a
    livello di package (import col prefisso del modulo -> directory),
    convenzione X_test.go. Import stdlib/terze parti mai indovinati."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ck-go-")
        for rel, content in GO_FIXTURE.items():
            path = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_go_panic_slice(self):
        """Frame assoluti del goroutine dump -> seed per suffisso; il blocco
        import di main.go porta i package interni, il package db arriva
        INTERO (db.go + util.go: l'unita' di import e' la directory)."""
        out = _run(self.root, "--symptom", GO_SYMPTOM).stdout
        self.assertIn("db/db.go — seed", out)
        self.assertIn("main.go — seed", out)
        self.assertIn("api/api.go — dipendenza", out)      # import a blocco
        self.assertIn("db/util.go — dipendenza", out)      # package = dir
        self.assertIn("db/db_test.go — test correlato", out)
        self.assertNotIn("extra/orphan.go", out.split("## fuori slice")[0])

    def test_go_aliased_single_import_edge(self):
        """`import alias "example.com/app/db"` (forma singola, con alias)
        -> arco verso il package db."""
        out = _run(self.root, "--seed", "api/api.go").stdout
        self.assertIn("api/api.go  <- seed esplicito", out)
        self.assertIn("db/db.go — dipendenza", out)

    def test_go_without_gomod_declares_no_edges(self):
        """Senza go.mod gli import interni non si risolvono senza indovinare:
        grafo vuoto, la slice resta sui seed (esclusione onesta, non crash)."""
        import shutil as _sh
        bare = tempfile.mkdtemp(prefix="ck-go-bare-")
        try:
            for rel in ("main.go", "db/db.go"):
                path = os.path.join(bare, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(GO_FIXTURE[rel])
            out = _run(bare, "--seed", "main.go").stdout
            self.assertIn("main.go  <- seed esplicito", out)
            self.assertNotIn("db/db.go — dipendenza", out)
        finally:
            _sh.rmtree(bare)


RUST_FIXTURE = {
    "src/main.rs": (
        "mod util;\nmod store;\n\n"
        "fn main() {\n"
        "    store::query();\n"
        "    util::fmt_all();\n"
        "    config::load();\n"     # stem ambiguo: due config.rs nel repo
        "}\n"),
    "src/util.rs": "pub fn fmt_all() {}\n",
    "src/store.rs": "pub fn query() { panic!(\"store offline\") }\n",
    "src/config_a/config.rs": "pub fn load() {}\n",
    "src/config_b/config.rs": "pub fn load() {}\n",
    "src/orphan.rs": "pub fn unused() {}\n",
    "tests/store_test.rs": "use crate::store;\n#[test]\nfn t() { store::query(); }\n",
}

C_FIXTURE = {
    "app.c": '#include "render.h"\n\nint main(void) { draw(); return 0; }\n',
    "render.h": "void draw(void);\n",
    "render.c": '#include "render.h"\nvoid draw(void) {}\n',
}


class TestGenericGraph(unittest.TestCase):
    """Il pavimento language-agnostic: linguaggi senza pack preciso passano
    dal mention-graph (nome file letterale + stem univoco), con la classe
    dell'arco DICHIARATA nel manifest. Mai indovinare sugli ambigui."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ck-rust-")
        for rel, content in RUST_FIXTURE.items():
            path = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_rust_panic_slice_with_declared_class(self):
        out = _run(self.root, "--symptom",
                   "thread 'main' panicked at src/store.rs:1:\n"
                   "store offline\n   at src/main.rs:5").stdout
        self.assertIn("src/store.rs — seed", out)
        self.assertIn("src/main.rs — seed", out)
        self.assertIn("src/util.rs — dipendenza", out)     # stem univoco
        self.assertIn("[grafo generico]", out)             # classe dichiarata
        self.assertIn("grafo generico (riferimenti testuali", out)  # header
        self.assertIn("tests/store_test.rs — test correlato", out)
        head = out.split("## fuori slice")[0]
        self.assertNotIn("src/orphan.rs", head)

    def test_ambiguous_stem_never_guessed(self):
        """Due config.rs nel repo: la menzione "config" non produce archi."""
        out = _run(self.root, "--symptom",
                   "panicked at src/main.rs:7").stdout
        head = out.split("## fuori slice")[0]
        self.assertNotIn("config_a/config.rs", head)
        self.assertNotIn("config_b/config.rs", head)

    def test_c_filename_literal_edge(self):
        """#include "render.h" -> arco per nome file letterale; render.c ha
        lo stem ambiguo (render.h/render.c) e NON arriva per stem."""
        base = tempfile.mkdtemp(prefix="ck-c-")
        try:
            for rel, content in C_FIXTURE.items():
                with open(os.path.join(base, rel), "w", encoding="utf-8") as f:
                    f.write(content)
            out = _run(base, "--seed", "app.c").stdout
            self.assertIn("app.c  <- seed esplicito", out)
            self.assertIn("render.h — dipendenza", out)
            head = out.split("## fuori slice")[0]
            self.assertNotIn("render.c —", head)
        finally:
            shutil.rmtree(base)


class TestFromDiff(unittest.TestCase):
    """--from-diff: il working set di una PR — i file modificati sono i seed,
    il grafo porta dipendenze, importatori (blast radius) e test correlati."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ck-diff-")
        for rel, content in FIXTURE.items():
            path = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        git_env = {**os.environ,
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def _git(*a):
            subprocess.run(["git", "-C", cls.root, *a], check=True,
                           capture_output=True, env=git_env)
        _git("init", "-q")
        _git("add", "-A")
        _git("commit", "-qm", "base")
        # modifica un sorgente e un file NON-sorgente
        with open(os.path.join(cls.root, "app/db.py"), "a") as f:
            f.write("# touch\n")
        with open(os.path.join(cls.root, "note.md"), "w") as f:
            f.write("# doc\n")
        _git("add", "-A")

    @classmethod
    def tearDownClass(cls):
        _util.rmtree_force(cls.root)           # .git ha oggetti read-only

    def test_diff_files_become_seeds(self):
        proc = _run(self.root, "--from-diff", "HEAD")
        out = proc.stdout
        self.assertIn("app/db.py", out)
        self.assertIn("file modificato nel diff (HEAD)", out)
        self.assertIn("app/util.py — dipendenza", out)   # blast radius
        self.assertIn("app/api.py — importatore", out)
        self.assertIn("tests/test_db.py — test correlato", out)
        self.assertIn("non-sorgente", proc.stderr)       # note.md scartato

    def test_diff_composes_with_symptom(self):
        out = _run(self.root, "--from-diff", "HEAD",
                   "--symptom", 'File "web/index.js", line 1').stdout
        self.assertIn("app/db.py", out)                  # dal diff
        self.assertIn("web/index.js", out)               # dal sintomo

    def test_not_a_git_repo_fails_declared(self):
        plain = tempfile.mkdtemp(prefix="ck-nogit-")
        self.addCleanup(shutil.rmtree, plain, True)
        with open(os.path.join(plain, "a.py"), "w") as f:
            f.write("X = 1\n")
        proc = _run(plain, "--from-diff", "HEAD")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--from-diff", proc.stderr)


class TestLearnedPriors(RepoSliceCase):
    """Loop T5 -> T2: i prior scritti da revealed --write-priors entrano
    nella slice come seed aggiuntivi e flag [freddo], mai come esclusioni."""

    def _priors_env(self, rec: dict) -> dict:
        path = os.path.join(tempfile.gettempdir(),
                            f"ck-priors-{os.getpid()}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({os.path.normpath(self.root): rec}, f)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return {"CK_PRIORS": "1", "CK_PRIORS_STATE": path}

    def test_prior_seed_added_with_declared_why(self):
        env = self._priors_env(
            {"seeds": [{"path": "app/unrelated.py", "sessions": 3}],
             "cold": []})
        out = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
        self.assertIn("app/unrelated.py", out)
        self.assertIn("prior appreso (T5: aperto fuori slice in 3 sessioni)",
                      out)
        self.assertIn("app/db.py — seed", out)         # i seed dal sintomo restano

    def test_cold_file_flagged_not_excluded(self):
        env = self._priors_env(
            {"seeds": [], "cold": [{"path": "app/util.py", "sessions": 2}]})
        out = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
        self.assertIn("app/util.py", out)              # resta in slice
        self.assertIn("freddo T5: mai aperto in 2 sessioni", out)

    def test_priors_alone_do_not_create_slice(self):
        """Senza seed dal sintomo il fail-safe resta: nessuna proiezione."""
        env = self._priors_env(
            {"seeds": [{"path": "app/unrelated.py", "sessions": 3}],
             "cold": []})
        proc = _run(self.root, "--symptom", "frase senza alcun sintomo",
                    env=env)
        self.assertIn("nessun seed riconosciuto", proc.stderr)

    def test_missing_prior_file_ignored(self):
        env = self._priors_env(
            {"seeds": [{"path": "app/cancellato.py", "sessions": 5}],
             "cold": []})
        out = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
        self.assertNotIn("cancellato", out)

    def test_priors_change_cache_key(self):
        cache = os.path.join(tempfile.gettempdir(),
                             f"ck-priors-cache-{os.getpid()}.json")
        self.addCleanup(lambda: os.path.exists(cache) and os.remove(cache))
        base = {"CK_SLICE_CACHE": "1", "CK_SLICE_CACHE_PATH": cache}
        first = _run(self.root, "--symptom", PY_SYMPTOM, env=base).stdout
        env = {**self._priors_env(
            {"seeds": [{"path": "app/unrelated.py", "sessions": 3}],
             "cold": []}), **base}
        second = _run(self.root, "--symptom", PY_SYMPTOM, env=env).stdout
        self.assertNotIn("[cache T2@", second)         # chiave diversa: no riuso
        self.assertIn("prior appreso", second)
        self.assertNotEqual(first, second)


DYN_FIXTURE = {
    "pk/__init__.py": "",
    "pk/registry.py": (
        "import importlib\n"
        "\n"
        "def load(name):\n"
        "    return importlib.import_module(name)\n"           # non letterale
        "\n"
        "def load_known():\n"
        "    return importlib.import_module('pk.backend')\n"   # letterale, nel repo
        "\n"
        "def load_missing():\n"
        "    return importlib.import_module('pk.nonesiste')\n"  # fuori repo
    ),
    # SOLO raggiungibile via import dinamico: il grafo statico lo escluderebbe
    "pk/backend.py": "VALUE = 1\n",
    "pk/other.py": "X = 2\n",
}


class TestDynamicReferences(unittest.TestCase):
    """T2 #2: il resolver supervisionato di riferimenti dinamici attacca il
    limite del grafo SOLO statico (importlib/__import__ invisibili). Additivo
    come i prior; mai indovina; punti ciechi dichiarati."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ck-dyn-")
        for rel, content in DYN_FIXTURE.items():
            path = os.path.join(cls.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_literal_dynamic_import_added_as_seed(self):
        """import_module('pk.backend') letterale -> backend.py entra come seed
        col call site, benche' il grafo statico non lo raggiunga."""
        out = _run(self.root, "--seed", "pk/registry.py").stdout
        self.assertIn('pk/backend.py  <- riferimento dinamico: '
                      'import "pk.backend"', out)
        self.assertIn("pk/registry.py:7", out)           # call site visibile
        self.assertIn("pk/backend.py — seed", out)

    def test_dynref_off_excludes_dynamic_target(self):
        """CK_DYNREF=0: senza resolver il grafo statico esclude backend.py
        (la prova che il limite #1 esisteva davvero)."""
        out = _run(self.root, "--seed", "pk/registry.py",
                   env={"CK_DYNREF": "0"}).stdout
        self.assertNotIn("pk/backend.py — seed",
                         out.split("## fuori slice")[0])
        self.assertNotIn("riferimento dinamico", out)

    def test_non_literal_arg_is_declared_blind_never_guessed(self):
        """import_module(name): argomento non letterale -> punto cieco
        dichiarato, MAI indovinato (regola FQCN, charter #3)."""
        out = _run(self.root, "--seed", "pk/registry.py").stdout
        self.assertIn("riferimenti dinamici non risolti", out)
        self.assertIn("pk/registry.py:4 (argomento non letterale)", out)
        # niente indovinelli: other.py non e' stato tirato dentro a caso
        self.assertNotIn("pk/other.py — seed", out)

    def test_literal_out_of_repo_is_blind_not_seed(self):
        """import_module('pk.nonesiste') letterale ma non risolvibile ->
        punto cieco, non un seed inventato."""
        out = _run(self.root, "--seed", "pk/registry.py").stdout
        self.assertIn('("pk.nonesiste" fuori repo o ambiguo)', out)

    def test_dynamic_refs_alone_do_not_create_slice(self):
        """Come i prior (charter #5): senza seed dal sintomo, nessuna
        proiezione — i riferimenti dinamici non si autoseminano."""
        proc = _run(self.root, "--symptom", "frase senza sintomo alcuno")
        self.assertIn("nessun seed riconosciuto", proc.stderr)

    def test_blind_spots_in_json(self):
        out = _run(self.root, "--seed", "pk/registry.py", "--json").stdout
        data = json.loads(out)
        self.assertTrue(any("argomento non letterale" in b
                            for b in data.get("dynamic_blind", [])))
        self.assertTrue(any(s["path"] == "pk/backend.py"
                            and "riferimento dinamico" in s["why"]
                            for s in data["seeds"]))

    def test_dynref_flag_changes_cache_key(self):
        cache = os.path.join(tempfile.gettempdir(),
                             f"ck-dyn-cache-{os.getpid()}.json")
        self.addCleanup(lambda: os.path.exists(cache) and os.remove(cache))
        base = {"CK_SLICE_CACHE": "1", "CK_SLICE_CACHE_PATH": cache}
        _run(self.root, "--seed", "pk/registry.py", env=base)
        off = _run(self.root, "--seed", "pk/registry.py",
                   env={**base, "CK_DYNREF": "0"}).stdout
        self.assertNotIn("[cache T2@", off)              # chiave diversa: no riuso


if __name__ == "__main__":
    unittest.main()
