"""Import con effetto: forza stdin/stdout/stderr a UTF-8.

Su Windows i processi figli aprono gli stream con la codepage locale
(cp1252 e simili), mentre l'harness parla UTF-8: un payload non-ASCII
manderebbe l'hook in eccezione -> no-op silenzioso. Su POSIX e' gia'
UTF-8 e la riconfigurazione non cambia nulla. Mai fatale.
"""
import sys

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                          # noqa: BLE001
        pass
