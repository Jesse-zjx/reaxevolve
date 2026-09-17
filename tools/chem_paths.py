"""Shim: load scripts/lib/chem_paths.py by absolute path (avoid self-import)."""
from __future__ import annotations

import importlib.util
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REAL = os.path.join(_PKG, "scripts", "lib", "chem_paths.py")

_spec = importlib.util.spec_from_file_location("chem_paths_real", _REAL)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

# Re-export public names into this module
for _k, _v in vars(_mod).items():
    if _k.startswith("__") and _k not in ("__doc__",):
        continue
    globals()[_k] = _v

# Keep a handle for debugging
_real_module = _mod
