#!/usr/bin/env python3
"""Snapshot an evolvable asset BEFORE mutation; append EVOLUTION_LOG.jsonl.

Revisions are identified by a monotonic sequence number per repository and a monotonic
version per asset — not by wall-clock time. What has to be checkable is the order of
revisions and the diff each one made, which the sequence and the snapshot give.

Usage:
  asset_snapshot.py --asset-id tools/guess/dry_proton_guess.py \\
      --path tools/guess/dry_proton_guess.py \\
      --trigger-evidence "..." --failure-mode "..." --intended-effect "..." --scope "..."
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVO = os.path.join(PKG, "evolution")
SNAP = os.path.join(EVO, "snapshots")
LOG = os.path.join(EVO, "EVOLUTION_LOG.jsonl")
LOG_MD = os.path.join(EVO, "EVOLUTION_LOG.md")
VERSIONS = os.path.join(PKG, "tools", "VERSIONS.json")
TAXONOMY = os.path.join(PKG, "policy", "failure_modes.json")


def load_taxonomy() -> tuple[set[str], str]:
    """Allowed failure-mode ids and the taxonomy version, from policy/.

    The taxonomy is a protected input: a free-text label makes "the same failure class"
    undecidable, and the transfer arm of the capability claim is exactly a comparison across
    independently drawn instances of one class.
    """
    with open(TAXONOMY) as fh:
        tax = json.load(fh)
    ids: set[str] = set()
    for section in ("chemistry", "process"):
        ids |= set((tax.get(section) or {}).get("modes") or {})
    return ids, str(tax.get("taxonomy_version") or "unknown")


def check_failure_modes(raw: str) -> tuple[list[str], str]:
    """Validate a comma-separated failure-mode list against the taxonomy."""
    ids, version = load_taxonomy()
    given = [x.strip() for x in (raw or "").split(",") if x.strip()]
    if not given:
        raise SystemExit("--failure-mode is required; see policy/failure_modes.md")
    bad = [x for x in given if x not in ids]
    if bad:
        raise SystemExit(
            f"failure mode(s) not in taxonomy {version}: {', '.join(bad)}\n"
            f"allowed: {', '.join(sorted(ids))}\n"
            f"see policy/failure_modes.md — the taxonomy is human-set and not evolvable"
        )
    return given, version


def load_versions():
    try:
        return json.load(open(VERSIONS))
    except Exception:
        return {}


def save_versions(v):
    json.dump(v, open(VERSIONS, "w"), indent=2)
    open(VERSIONS, "a").write("\n")


def normalize_asset_id(asset_id: str) -> str:
    """Asset identity is the skill or the tool file, not whichever alias was emitted.

    `.skills/x`, `skills/x` and `.skills/x/SKILL.md` are one asset. Letting all three
    through produced parallel version lineages for the same file.
    """
    rel = (asset_id or "").replace("\\", "/").strip().lstrip("./")
    if rel.startswith("skills/"):
        rel = "." + rel
    if rel.startswith(".skills/"):
        parts = [p for p in rel.split("/") if p]
        return "/".join(parts[:2])
    return rel


def next_seq() -> int:
    if not os.path.isfile(LOG):
        return 1
    n = 0
    for line in open(LOG):
        if not line.strip():
            continue
        try:
            n = max(n, int(json.loads(line).get("seq") or 0))
        except Exception:
            continue
    return n + 1


def _slot(vers, asset_id):
    """Locate the (section, key) that already tracks this asset in VERSIONS.json.

    Versions are stored as {"skills": {...}, "tools": {...}} with values like "v0".
    Writing a flat top-level key would leave two disagreeing records of one asset.
    """
    rel = asset_id.strip("./")
    for section in ("skills", "tools"):
        table = vers.get(section)
        if not isinstance(table, dict):
            continue
        for key in table:
            if rel == key or rel.endswith("/" + key) or rel == f"{section}/{key}":
                return section, key
            # ".skills/qm-execution" ↔ skills["qm-execution"]
            if rel.split("/")[-1] == key.split("/")[-1] and section == "skills":
                return section, key
    return None, None


def _parse_v(val):
    if isinstance(val, int):
        return val
    s = str(val or "").strip().lstrip("vV")
    return int(s) if s.isdigit() else 0


def read_version(vers, asset_id):
    section, key = _slot(vers, asset_id)
    if section:
        return _parse_v(vers[section][key]), (section, key)
    return _parse_v(vers.get(asset_id, 0)), None


def write_version(vers, asset_id, slot, after):
    if slot:
        section, key = slot
        vers[section][key] = f"v{after}"
        return
    # New asset: keep VERSIONS.json sectioned rather than growing a flat key.
    rel = asset_id.strip("./")
    section = "skills" if rel.startswith(".skills/") or rel.startswith("skills/") else "tools"
    key = rel.split("/", 1)[1] if rel.startswith((".skills/", "skills/", "tools/")) else rel
    vers.setdefault(section, {})[key] = f"v{after}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset-id", required=True, help="stable id, e.g. guess/dry_proton_guess")
    ap.add_argument("--path", required=True, help="file or directory to snapshot")
    ap.add_argument("--trigger-evidence", default="unknown")
    ap.add_argument("--failure-mode", default="unknown")
    ap.add_argument("--intended-effect", default="unknown")
    ap.add_argument("--scope", default="unknown")
    ap.add_argument("--diff", default="unknown")
    ap.add_argument("--activation-point", default="unknown")
    ap.add_argument(
        "--revision-class",
        choices=("qm_feedback", "plumbing", "reorganization"),
        default="qm_feedback",
        help="qm_feedback: driven by recorded QM failures; plumbing: path/format fix; "
        "reorganization: rename/split/merge of the asset surface",
    )
    ap.add_argument("--bump", action="store_true", help="increment tools/VERSIONS.json")
    ap.add_argument(
        "--snapshot-only",
        action="store_true",
        help="copy the pre-change asset and stop: no version bump, no ledger entry. Use this "
        "before attempting a patch, then --record once the patch has been validated.",
    )
    ap.add_argument(
        "--record",
        metavar="SNAPSHOT_DIR",
        help="append the ledger entry for an earlier --snapshot-only, and bump if the "
        "outcome is `applied`",
    )
    ap.add_argument(
        "--outcome",
        choices=("applied", "rolled_back"),
        default="applied",
        help="rolled_back records the attempt without bumping: a revision that did not land "
        "must not appear in the ledger as one that did",
    )
    a = ap.parse_args()

    # Reflect is closed during a fixed-asset comparison or a replay: a revision landing mid-arm
    # would mean the arm was no longer a comparison between two asset versions. scripts/eval/
    # arm_runner.py sets this for the duration, and detects a violation afterwards through the
    # ledger and asset digests; refusing here is the prevention half.
    if a.bump and os.environ.get("CHEM_REFLECT_CLOSED") == "1":
        raise SystemExit(
            "refusing to bump: CHEM_REFLECT_CLOSED is set, so an evaluation arm is running and no "
            "revision may land. Unset it only outside an arm."
        )

    os.makedirs(SNAP, exist_ok=True)
    asset_id = normalize_asset_id(a.asset_id)
    vers = load_versions()
    before, slot = read_version(vers, asset_id)
    modes, taxonomy_version = check_failure_modes(a.failure_mode)

    # ---- phase 1: snapshot the pre-change asset ----
    if a.record:
        dest = a.record if os.path.isabs(a.record) else os.path.join(PKG, a.record)
        if not os.path.isdir(dest):
            raise SystemExit(f"--record: no such snapshot directory: {a.record}")
        m = re.match(r"(\d+)__", os.path.basename(dest.rstrip("/")))
        seq = int(m.group(1)) if m else next_seq()
    else:
        seq = next_seq()
        tag = asset_id.replace("/", "_").lstrip(".")
        dest = os.path.join(SNAP, f"{seq:03d}__{tag}__v{before}")
        os.makedirs(dest, exist_ok=True)
        src = a.path if os.path.isabs(a.path) else os.path.join(PKG, a.path)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, os.path.basename(src.rstrip("/"))), dirs_exist_ok=True)
        else:
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
        if a.snapshot_only:
            print(json.dumps({"snapshot": os.path.relpath(dest, PKG), "seq": seq,
                              "asset_id": asset_id, "version_before": before}, indent=2))
            return 0

    # ---- phase 2: the revision landed (or did not); record it ----
    applied = a.outcome == "applied"
    after = before + 1 if (a.bump and applied) else before
    if a.bump and applied:
        write_version(vers, asset_id, slot, after)
        save_versions(vers)

    rec = {
        "seq": seq,
        "class": a.revision_class,
        "outcome": a.outcome,
        "asset_id": asset_id,
        "asset_version_before": before,
        "asset_version_after": after,
        "failure_mode": modes,
        "taxonomy_version": taxonomy_version,
        "trigger_evidence": a.trigger_evidence,
        "intended_effect": a.intended_effect,
        "scope": a.scope,
        "activation_point": a.activation_point,
        "diff": a.diff,
        "snapshot": os.path.relpath(dest, PKG),
        # Filled by scripts/reflect/close_revisions.py once downstream evidence exists.
        "first_downstream_use": None,
        "expectation_met": None,
        "asset_versions_at_revision": {
            **{f".skills/{k}": v for k, v in (vers.get("skills") or {}).items()},
            **{f"tools/{k}": v for k, v in (vers.get("tools") or {}).items()},
        },
        "vector_schema": vers.get("schema"),
        "asset_set": vers.get("asset_set"),
    }
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(LOG_MD, "a") as f:
        arrow = f"v{before}→v{after}" if applied else f"v{before} (rolled back)"
        f.write(
            f"- `{seq:03d}` **{asset_id}** {arrow} [{a.revision_class}] "
            f"({','.join(modes)}@{taxonomy_version}): {a.intended_effect} "
            f"(snap `{os.path.relpath(dest, PKG)}`)\n"
        )
    print(json.dumps(rec, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
