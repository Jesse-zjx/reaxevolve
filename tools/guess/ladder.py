"""Guess ladder: reaction_kind → ordered guess generators.

The archived dispatcher used to consume this table. The live Validate stage
(`loop/skill_runner.py` → `tools/workflow/run_qm_step.py`) still uses the same
generators when a skill names them. Geometry helpers live in `tools/geometry/`.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# reaction_kind -> ordered guess generator modules (first wins; fallbacks follow)
LADDER: Tuple[Tuple[FrozenSet[str], Tuple[str, ...]], ...] = (
    (frozenset({"dehydration", "aromatization", "dehydration_aromatization"}), ("constrained_scan_guess",)),
    (frozenset({"retro_aldol"}), ("constrained_scan_guess", "dual_scan")),
    (frozenset({"ring_closure", "ring_opening"}), ("dual_scan",)),
    (
        frozenset({
            "keto_to_enol",
            "enol_to_keto",
            "tautomerization",
            "enolization",
            "ketonization",
        }),
        ("dry_proton_guess", "water_relay_guess"),
    ),
    (frozenset({"isomerization", "aldose_ketose", "ketose_aldose"}), ("scan2d", "scan2d_guess")),
)

DEHY = LADDER[0][0]
TAUT = LADDER[3][0]
ISO = LADDER[4][0]

GENERATOR_MODULES = (
    "auto_guess",
    "constrained_scan_guess",
    "dry_proton_guess",
    "water_relay_guess",
    "neb_guess",
    "scan2d",
    "scan2d_guess",
    "proton_scan",
    "smi_to_xyz",
)


def import_generators():
    """Best-effort import of guess generators (for tooling / smoke tests)."""
    import importlib

    out: Dict[str, object] = {}
    for name in GENERATOR_MODULES:
        try:
            out[name] = importlib.import_module(name)
        except ImportError:
            pass
    return out
