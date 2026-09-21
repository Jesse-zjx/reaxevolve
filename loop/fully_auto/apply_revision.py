#!/usr/bin/env python3
"""Apply a Reflect revision under the evolvable whitelist, with snapshot rollback.

The whitelist is the editable asset surface: declarative Skills, and Tools that are
guess/scan templates, scheduling parameters, routine composition, and self-check
thresholds. It deliberately excludes `policy/` (acceptance clauses and the QM
protocol), `scripts/` (graph writers, verdict writer, evidence parsers) and `loop/`
(scheduling), so a revision can change what gets proposed and in what order but cannot
change what counts as a pass.

`tools/expand/` and `tools/screen/` are on the list on purpose: the reaction templates
and the candidate scoring function encode chemistry learned from QM feedback, and that
is exactly the kind of asset this loop is meant to revise. They can only reorder or
add proposals — status is written solely by scripts/validate/verdict_writer.py under
policy/acceptance, so a bad template or a bad weight costs compute and cannot
manufacture a verdict.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))

ALLOWED_PREFIXES = (
    ".skills/",
    "tools/guess/",
    "tools/expand/",
    "tools/screen/",
    "tools/workflow/",
    "tools/VERSIONS.json",
    "tools/record_update.py",
    # tools/geometry/ is listed per file, not by prefix: two of its modules read the
    # evidence and must not be writable. See PROTECTED below.
    "tools/geometry/builder.py",
    "tools/geometry/inquire.py",
    "tools/geometry/smi_to_xyz.py",
    "tools/geometry/map_reaction_atoms.py",
    "tools/builder.py",
    "tools/inquire.py",
    "tools/map_reaction_atoms.py",
    "tools/smi_to_xyz.py",
)

# Evidence parsers. These decide what the calculation *says* — the frequencies and the
# endpoint identities that clauses 2 and 3 are evaluated against — so a revision to one could
# change a verdict without changing any chemistry. The method's write matrix puts them in the
# protected set for exactly that reason, and the argument that an evolvable tool "cannot dress
# a wrong physical result up as a pass" holds for templates and schedulers but not for the
# module that reads the frequency out of the output file.
#
# Guess-side geometry tools stay evolvable: they propose structures, they do not judge them.
PROTECTED = (
    "tools/geometry/parse_orca_output.py",
    "tools/geometry/xyz_to_smiles.py",
    "tools/parse_orca_output.py",
    "tools/xyz_to_smiles.py",
)

# Modules whose revision changes what Explore proposes. A syntax check is not enough:
# a scorer that raises at call time empties the queue for every later round, and the
# loop would keep running with nothing to validate. These get exercised on fixed input
# before the revision is allowed to stand.
_SMOKE_CALLABLE = {
    "tools/expand/templates_expand.py",
    "tools/screen/diversity.py",
}


def _known_skill_names() -> set[str]:
    root = os.path.join(PKG, ".skills")
    if not os.path.isdir(root):
        return set()
    return {n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))}


def normalize_rel(rel: str) -> str:
    """Map LLM path aliases onto the on-disk whitelist layout.

    Models often emit `skills/...` instead of `.skills/...`, a skill directory
    without `SKILL.md`, or a bare name like `generate-ts-guesses/SKILL.md`.
    Those are not extra folders on disk — only `.skills/` exists.
    """
    rel = (rel or "").replace("\\", "/").strip().lstrip("./")
    if rel.startswith("skills/") and not rel.startswith(".skills/"):
        rel = "." + rel
    known = _known_skill_names()
    first = rel.split("/")[0] if rel else ""
    if first in known and not rel.startswith(".skills/") and not rel.startswith("tools/"):
        rest = "/".join(p for p in rel.split("/")[1:] if p)
        rel = f".skills/{first}/{rest}" if rest else f".skills/{first}"
    if rel.startswith(".skills/"):
        parts = [p for p in rel.split("/") if p]
        if len(parts) == 2:  # .skills/<name>
            cand = os.path.join(PKG, rel)
            if os.path.isdir(cand):
                rel = rel.rstrip("/") + "/SKILL.md"
        elif len(parts) == 1:
            rel = f".skills/{parts[0]}/SKILL.md"
    return rel


def allowed(rel: str) -> bool:
    rel = normalize_rel(rel)
    if rel in PROTECTED:
        return False
    if rel == "tools/VERSIONS.json":
        return True
    return any(rel.startswith(p) for p in ALLOWED_PREFIXES if p.endswith("/")) or rel in ALLOWED_PREFIXES


def syntax_ok(path: str) -> tuple[bool, str]:
    if not path.endswith(".py"):
        return True, "non-py"
    try:
        ast.parse(open(path).read())
        return True, "ok"
    except SyntaxError as e:
        return False, str(e)


# Fixed probe: open-chain glucose. Any revision of the enumerator or the scorer must
# still turn this into scored, atom-conserving candidates.
_PROBE_SMILES = "O=CC(O)C(O)C(O)C(O)CO"


def expander_smoke_ok(rel: str) -> tuple[bool, str]:
    """Run the revised enumerator/scorer on fixed input before accepting the revision."""
    if rel not in _SMOKE_CALLABLE:
        return True, "not-callable-asset"
    code = r"""
import json, os, sys
PKG = os.environ["REAXEVOLVE_PKG"]
sys.path[:0] = [
    os.path.join(PKG, "scripts", "lib"),
    os.path.join(PKG, "loop"),
    os.path.join(PKG, "tools", "expand"),
    os.path.join(PKG, "tools", "screen"),
]
import templates_expand as TE
import mass_balance as MB
probe = os.environ["REAXEVOLVE_PROBE"]
cands = TE.expand([TE.canon(probe)], set())
if not isinstance(cands, list) or not cands:
    print("expand() returned nothing for the probe species"); raise SystemExit(1)
for c in cands[:25]:
    for k in ("reactant", "product", "reaction_kind", "score"):
        if k not in c:
            print("candidate missing key " + k); raise SystemExit(1)
    float(c["score"])
    if not MB.ok(c["reactant"], c["product"], c.get("coproduct")):
        print("candidate does not conserve atoms: %s >> %s" % (c["reactant"], c["product"]))
        raise SystemExit(1)
print("ok n=%d" % len(cands))
"""
    env = dict(os.environ, REAXEVOLVE_PKG=PKG, REAXEVOLVE_PROBE=_PROBE_SMILES)
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=PKG, env=env, text=True, capture_output=True
    )
    if r.returncode != 0:
        return False, ((r.stdout or "") + (r.stderr or ""))[-600:]
    return True, (r.stdout or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True, help="JSON file from client.propose")
    ap.add_argument("--smoke", action="store_true", help="run scripts/smoke_test.py after apply")
    a = ap.parse_args()
    prop = json.load(open(a.proposal))
    if prop.get("action") != "revise":
        print(json.dumps({"ok": True, "skipped": True, "proposal": prop.get("action")}))
        return 0

    raw_path = prop.get("path") or ""
    rel = normalize_rel(raw_path)
    asset_id = prop.get("asset_id") or rel
    if isinstance(asset_id, str):
        asset_id = normalize_rel(asset_id)

    if rel in PROTECTED:
        print(json.dumps({
            "ok": False,
            "error": "protected evidence parser",
            "path": rel,
            "raw_path": raw_path,
            "why": "this module decides what the calculation says; it is outside the editable "
                   "surface by design (see PROTECTED in this file and policy/)",
        }))
        return 2
    if not allowed(rel):
        print(json.dumps({"ok": False, "error": "path not on whitelist", "path": rel, "raw_path": raw_path}))
        return 2
    abs_path = os.path.join(PKG, rel)
    if not os.path.exists(abs_path):
        print(json.dumps({"ok": False, "error": "missing path", "path": rel, "raw_path": raw_path}))
        return 2

    # Persist normalized path so archives match what we wrote.
    prop["path"] = rel
    prop["asset_id"] = asset_id
    prop["path_normalized_from"] = raw_path
    json.dump(prop, open(a.proposal, "w"), indent=2)
    open(a.proposal, "a").write("\n")

    # The ledger entry and the version bump come *after* the patch has been validated. Doing
    # them first meant a revision that failed its checks and was rolled back still appeared in
    # the ledger as one that landed, and VERSIONS.json claimed a version no file had — in the
    # record that is the primary evidence for the capability claim.
    def snapshot_args(*extra):
        return [
            sys.executable,
            os.path.join(PKG, "scripts", "reflect", "asset_snapshot.py"),
            "--asset-id", asset_id,
            "--path", rel,
            "--trigger-evidence", str(prop.get("trigger_evidence") or "reflect"),
            "--failure-mode", str(prop.get("failure_mode") or ""),
            "--intended-effect", str(prop.get("intended_effect") or "unknown"),
            "--scope", str(prop.get("scope") or "reflect"),
            "--diff", "reflect_proposal",
            "--activation-point", rel,
            *extra,
        ]

    snap = subprocess.run(
        snapshot_args("--snapshot-only"), cwd=PKG, text=True, capture_output=True
    )
    if snap.returncode != 0:
        # A failure-mode outside the taxonomy lands here: refuse rather than record free text.
        print(json.dumps({
            "ok": False,
            "error": "snapshot refused",
            "detail": (snap.stderr or snap.stdout or "").strip()[-500:],
        }))
        return 7
    try:
        snapshot_dir = json.loads(snap.stdout)["snapshot"]
    except (json.JSONDecodeError, KeyError):
        print(json.dumps({"ok": False, "error": "unparseable snapshot output",
                          "tail": (snap.stdout or "")[-300:]}))
        return 7

    def record(outcome: str, reason: str | None = None):
        extra = ["--record", snapshot_dir, "--outcome", outcome]
        if outcome == "applied":
            extra.append("--bump")
        r = subprocess.run(snapshot_args(*extra), cwd=PKG, text=True, capture_output=True)
        if r.returncode != 0:
            sys.stderr.write((r.stderr or r.stdout or "")[-400:])
        return reason

    backup = abs_path + ".bak_fully_auto"
    shutil.copy2(abs_path, backup)

    diff = prop.get("diff_unified") or ""
    if diff.startswith("FULL:\n"):
        open(abs_path, "w").write(diff[len("FULL:\n") :])
    elif diff.startswith("FULL:"):
        open(abs_path, "w").write(diff[len("FULL:") :].lstrip("\n"))
    elif diff.strip():
        r = subprocess.run(
            ["patch", "-p1", "--forward", "--batch"],
            cwd=PKG,
            input=diff,
            text=True,
            capture_output=True,
        )
        if r.returncode != 0:
            # Last resort: whole-file dump without FULL: prefix (common for SKILL.md).
            looks_full = rel.endswith((".md", ".py")) and (
                diff.lstrip().startswith("#")
                or diff.lstrip().startswith('"""')
                or diff.lstrip().startswith("---")
            )
            if looks_full and "\n@@" not in diff and not diff.lstrip().startswith("diff "):
                open(abs_path, "w").write(diff)
            else:
                shutil.copy2(backup, abs_path)
                record("rolled_back")
                print(json.dumps({
                    "ok": False,
                    "error": "patch failed",
                    "restored": True,
                    "recorded_as": "rolled_back",
                    "stderr": (r.stderr or "")[-500:],
                }))
                return 3
    else:
        # Nothing was written, so there is no revision attempt to record.
        print(json.dumps({"ok": False, "error": "empty diff"}))
        return 2

    ok, msg = syntax_ok(abs_path)
    if not ok:
        shutil.copy2(backup, abs_path)
        record("rolled_back")
        print(json.dumps({"ok": False, "error": "syntax", "detail": msg, "restored": True,
                          "recorded_as": "rolled_back"}))
        return 4
    ok, msg = expander_smoke_ok(rel)
    if not ok:
        shutil.copy2(backup, abs_path)
        record("rolled_back")
        print(
            json.dumps(
                {"ok": False, "error": "expander smoke failed", "detail": msg,
                 "restored": True, "recorded_as": "rolled_back"}
            )
        )
        return 6
    if a.smoke:
        r = subprocess.run(
            [sys.executable, os.path.join(PKG, "scripts", "smoke_test.py")],
            cwd=PKG,
        )
        if r.returncode != 0:
            shutil.copy2(backup, abs_path)
            record("rolled_back")
            print(json.dumps({"ok": False, "error": "smoke failed", "restored": True,
                              "recorded_as": "rolled_back"}))
            return 5
    record("applied")
    os.remove(backup)
    print(json.dumps({"ok": True, "path": rel, "asset_id": asset_id, "raw_path": raw_path}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
