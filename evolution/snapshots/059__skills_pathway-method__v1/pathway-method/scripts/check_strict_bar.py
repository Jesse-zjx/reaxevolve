#!/usr/bin/env python3
"""Shim — canonical: policy/acceptance/check_strict_bar.py"""
import runpy
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[3]
_CANON = _PKG / "policy" / "acceptance" / "check_strict_bar.py"
if not _CANON.is_file():
    raise SystemExit(f"missing canonical bar checker: {_CANON}")
sys.argv[0] = str(_CANON)
runpy.run_path(str(_CANON), run_name="__main__")
