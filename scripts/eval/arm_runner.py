#!/usr/bin/env python3
"""Run the loop against a chosen asset set, with Reflect closed and a core-hour cap.

Both preregistered comparisons need this and neither could run without it. The fixed-asset
comparison runs the same task under two asset sets; the replay runs matched instances under two
versions of one asset. In each case the requirement is identical: everything except the asset under
test must be the same, and nothing may be revised while the measurement is happening.

Three guarantees, each checked rather than assumed:

**Isolation.** The arm runs in a materialised tree, not in the repository. Reading the live tree
would make the initial arm run against final-set skills, and a run that wrote to Graph Memory would
contaminate the state the other arm starts from.

**Reflect closed.** No revision may land during an arm. The ledger's length and digest are recorded
before and after and compared; if an arm somehow revised an asset, the arm is void, because it would
no longer be a comparison between two asset versions.

**Accounting.** Core-hours are summed from the attempt records the arm produces and checked against
the cap, so "did not deliver" can be distinguished from "ran out of budget".

  python scripts/eval/arm_runner.py --set initial --task preregistration/c2_route.json --dry-run
  python scripts/eval/arm_runner.py --set final   --task preregistration/c2_route.json --cap-core-h 180
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PKG, "loop"))
import asset_set as AS  # noqa: E402

# Copied into every arm: the framework both arms share. Kept explicit rather than "everything
# except assets", so that adding a directory to the repository cannot silently change what an arm
# considers shared.
FRAMEWORK = ("policy", "scripts", "loop", "tools", ".skills", ".agentcfg", "graph")
# Never copied: other arms' scratch, the run tree, and anything holding results.
NEVER = ("runs", "evidence", "deposits", "experiments", "evolution", "assets", "node_modules")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ledger_digest() -> tuple[int, str]:
    """Length and content digest of the revision ledger, to prove nothing was revised."""
    p = os.path.join(PKG, "evolution", "EVOLUTION_LOG.jsonl")
    if not os.path.isfile(p):
        return 0, ""
    data = open(p, "rb").read()
    n = sum(1 for line in data.splitlines() if line.strip())
    return n, hashlib.sha256(data).hexdigest()[:16]


def asset_digest(dest: str) -> tuple[int, str]:
    """Digest of every asset file in the arm, to prove none changed while the arm ran.

    The ledger digest is not enough. Skills run with `write` and `edit` tools, so an arm can modify
    its own SKILL.md directly, without going through the bump path and without touching the ledger —
    and that is precisely the protocol's prohibition on editing assets during evaluation. Hashing the
    arm's own assets is what actually detects it.
    """
    h = hashlib.sha256()
    n = 0
    for sub in (".skills", "tools"):
        base = os.path.join(dest, sub)
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(files):
                if f.endswith(".pyc"):
                    continue
                p = os.path.join(root, f)
                h.update(os.path.relpath(p, dest).encode())
                h.update(open(p, "rb").read())
                n += 1
    return n, h.hexdigest()[:16]


def materialise(set_name: str, dest: str) -> dict:
    """Build an isolated tree running `set_name`'s assets on the shared framework."""
    if os.path.exists(dest):
        raise SystemExit(f"refusing to overwrite {dest}")
    os.makedirs(dest)
    src_assets = AS.set_root(set_name)
    live = AS.live_set_name()

    for d in FRAMEWORK:
        s = os.path.join(PKG, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest, d), symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "sessions", "*.pyc"))
    for f in (".env", "package.json"):
        s = os.path.join(PKG, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, f))
    nm = os.path.join(PKG, "node_modules")
    if os.path.isdir(nm):
        # Symlinked, not copied: it is large, it is not part of what differs between arms, and a
        # copy per arm would make the disk cost of a comparison dominate its compute cost.
        os.symlink(nm, os.path.join(dest, "node_modules"))

    # Overlay the arm's assets. For the set the live tree already carries this is a no-op, which is
    # why it is expressed as an overlay rather than a conditional: the two cases stay identical.
    if set_name != live:
        for d in (".skills", "tools"):
            s = os.path.join(src_assets, d)
            if os.path.isdir(s):
                t = os.path.join(dest, d)
                shutil.rmtree(t, ignore_errors=True)
                shutil.copytree(s, t, symlinks=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # The role map, and only the role map, out of assets/. The arm must resolve roles by itself —
    # a dry run that resolved them in the parent process would verify nothing about the arm — but
    # copying assets/ wholesale would let the arm read the other set's skills.
    os.makedirs(os.path.join(dest, "assets"), exist_ok=True)
    shutil.copy2(os.path.join(PKG, "assets", "roles.json"),
                 os.path.join(dest, "assets", "roles.json"))

    # Empty state: the arm starts from the shared graph but writes its own results.
    for d in ("runs", "evidence/state/loop", "evidence/audit"):
        os.makedirs(os.path.join(dest, d), exist_ok=True)

    vv = AS.version_vector(set_name, dest if set_name == live else None)
    return {
        "asset_set": set_name,
        "root": dest,
        "declared_set_in_tree": json.load(
            open(os.path.join(dest, "tools", "VERSIONS.json"))
        ).get("asset_set"),
        "n_skills": len(vv.get("skills") or {}),
        "n_tools": len(vv.get("tools") or {}),
    }


def overlay_snapshot(dest: str, asset_id: str, snapshot: str) -> dict:
    """Replace one asset in a materialised arm with its content at a past version.

    This is the replay's `before` arm. What it can and cannot do is a property of the snapshots, not
    of this function: 55 of 59 hold only SKILL.md, so the asset is not restored whole. Companion
    files stay at the arm's own content, which is what keeps the comparison honest — no revision in
    the ledger touched a companion file, so holding them fixed leaves the arms differing only in the
    text each revision actually changed.

    The report says which files came from the snapshot and which were left alone, so a reader does
    not have to take that on trust.
    """
    src = os.path.join(PKG, snapshot)
    if not os.path.isdir(src):
        raise SystemExit(f"snapshot not found: {snapshot}")
    target = os.path.join(dest, asset_id)
    replaced, kept = [], []
    if os.path.isfile(target) or asset_id.endswith(".py"):
        # A single-file asset: the snapshot holds the whole thing.
        files = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))]
        if len(files) != 1:
            raise SystemExit(f"{snapshot} holds {len(files)} files for single-file asset {asset_id}")
        shutil.copy2(os.path.join(src, files[0]), target)
        replaced.append(asset_id)
    else:
        if not os.path.isdir(target):
            raise SystemExit(f"{asset_id} is not present in this arm: wrong asset set?")
        snap_names = {
            os.path.relpath(os.path.join(r, f), src)
            for r, _, fs in os.walk(src) for f in fs
        }
        for rel in sorted(snap_names):
            shutil.copy2(os.path.join(src, rel), os.path.join(target, rel))
            replaced.append(os.path.join(asset_id, rel))
        for r, _, fs in os.walk(target):
            for f in fs:
                rel = os.path.relpath(os.path.join(r, f), target)
                if rel not in snap_names:
                    kept.append(os.path.join(asset_id, rel))
    return {
        "asset_id": asset_id,
        "snapshot": snapshot,
        "restored_from_snapshot": replaced,
        "left_at_arm_content": sorted(kept),
        "whole_asset_restored": not kept,
    }


def verify_arm(info: dict, set_name: str) -> list[str]:
    """The materialised tree really is the arm it claims to be."""
    problems = []
    # Absolute, so the checks do not depend on the caller's working directory: a relative root
    # silently became a doubled path when this was exercised from the repository root.
    dest = os.path.abspath(info["root"])
    if info["declared_set_in_tree"] != set_name:
        problems.append(
            f"tree declares asset_set={info['declared_set_in_tree']!r}, arm is {set_name!r}: "
            "the overlay did not replace tools/VERSIONS.json"
        )
    try:
        for role in ("guess_generation", "failure_diagnosis"):
            AS.skill_dirs(set_name, role, root=dest)
    except Exception as e:
        problems.append(f"role does not resolve inside the arm: {e}")
    # The arm must not be able to read the other set's assets. assets/ exists but must hold only
    # the role map: anything else there is a set the arm could read.
    leaked = [
        e for e in os.listdir(os.path.join(dest, "assets"))
        if e != "roles.json"
    ] if os.path.isdir(os.path.join(dest, "assets")) else []
    if leaked:
        problems.append(f"the arm can see assets/{{{','.join(leaked)}}}: another set's skills are "
                        "reachable")
    for d in ("deposits", "experiments"):
        if os.path.exists(os.path.join(dest, d)):
            problems.append(f"the arm can see {d}/: deposited answers are reachable")

    # Resolve roles by running the arm's own copy, in the arm's own directory. Resolving them in
    # this process would read the repository's modules and prove nothing about the arm.
    probe = sh(
        [sys.executable, os.path.join(dest, "loop", "asset_set.py"), "--set", set_name],
        cwd=dest,
    )
    if probe.returncode != 0:
        problems.append(
            "the arm cannot resolve its own roles: "
            + (probe.stderr or probe.stdout).strip().splitlines()[-1][:160]
        )
    return problems


def spent_core_h(dest: str) -> float:
    """Core-hours from this arm's own attempt records."""
    total = 0.0
    for root, _, files in os.walk(os.path.join(dest, "runs")):
        for f in files:
            if f != "strict_cache.json":
                continue
            try:
                blob = json.load(open(os.path.join(root, f)))
            except Exception:
                continue
            for v in blob.values():
                w, n = v.get("wall_s"), v.get("nprocs") or 16
                if w:
                    total += (w / 3600.0) * n
    return round(total, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", dest="name", required=True, help="asset set to run (initial | final)")
    ap.add_argument("--task", help="JSON task file: the steps this arm must rebuild")
    ap.add_argument("--cap-core-h", type=float, default=180.0)
    ap.add_argument("--nprocs", type=int, default=16)
    ap.add_argument("--wall-s", type=int, default=5400)
    ap.add_argument("--max-rounds", type=int, default=3,
                    help="guess rounds per step, identical across arms by construction")
    ap.add_argument("--workdir", default=None, help="where to materialise (default: runs/arms/<set>)")
    ap.add_argument("--snapshot-asset", metavar="ASSET_ID",
                    help="replay's `before` arm: roll this asset back to --snapshot")
    ap.add_argument("--snapshot", metavar="PATH",
                    help="evolution/snapshots/<entry> to roll --snapshot-asset back to")
    ap.add_argument("--dry-run", action="store_true",
                    help="materialise and verify the arm, then stop before any QM")
    ap.add_argument("--keep", action="store_true", help="keep the materialised tree afterwards")
    a = ap.parse_args()

    dest = a.workdir or os.path.join(PKG, "runs", "arms", a.name)
    shutil.rmtree(dest, ignore_errors=True)

    print(f"== materialising arm {a.name!r} ==")
    info = materialise(a.name, dest)
    print(f"  root:   {os.path.relpath(dest, PKG)}")
    print(f"  assets: {info['n_skills']} skills, {info['n_tools']} tools "
          f"(tree declares {info['declared_set_in_tree']!r})")

    rollback = None
    if a.snapshot_asset or a.snapshot:
        if not (a.snapshot_asset and a.snapshot):
            print("--snapshot-asset and --snapshot must be given together")
            return 2
        rollback = overlay_snapshot(dest, a.snapshot_asset, a.snapshot)
        print(f"== rolled {a.snapshot_asset} back to {a.snapshot} ==")
        for f in rollback["restored_from_snapshot"]:
            print(f"  from snapshot:  {f}")
        for f in rollback["left_at_arm_content"]:
            print(f"  left as-is:     {f}")
        if not rollback["whole_asset_restored"]:
            print("  the asset is NOT restored whole. The snapshot does not contain every file the")
            print("  asset carries; the rest stay at this arm's content, identical in both arms.")

    print("== verifying the arm is what it claims ==")
    problems = verify_arm(info, a.name)
    for p in problems:
        print(f"  PROBLEM {p}")
    if problems:
        print("\narm is not usable; nothing was run")
        return 1
    for role in ("guess_generation", "failure_diagnosis"):
        dirs = AS.skill_dirs(a.name, role, root=dest)
        print(f"  {role:<20} {', '.join(os.path.basename(d) for d in dirs)}")
    print("  isolation: assets/, deposits/, experiments/ not reachable from the arm")

    n_before, d_before = ledger_digest()
    na_before, da_before = asset_digest(dest)
    print(f"  ledger before: {n_before} revisions, digest {d_before}")
    print(f"  assets before: {na_before} files, digest {da_before}")

    if a.dry_run:
        print("\n== dry run: stopping before QM ==")
        print("  the arm materialises, declares the right set, resolves both roles, and cannot")
        print("  reach the other arm's assets or the deposited answers.")
        if not a.keep:
            shutil.rmtree(dest, ignore_errors=True)
            print(f"  removed {os.path.relpath(dest, PKG)}")
        return 0

    if not a.task:
        print("\n--task is required for a real run")
        return 2

    task_blob = json.load(open(a.task))
    steps = task_blob.get("steps") or []
    if not steps:
        print(f"{a.task} contains no steps")
        return 2

    # Every step must be one the preregistration locks. Deriving the task from the protocol is only
    # worth something if a hand-edited task cannot be run: this is the check that makes it so.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_task as MT  # noqa: E402

    allowed = MT.preregistered_steps()
    stray = [
        (s.get("reactant"), s.get("product")) for s in steps
        if (s.get("reactant"), s.get("product")) not in allowed
    ]
    if stray:
        print(f"\nrefusing to run: {len(stray)} step(s) in {os.path.relpath(a.task, PKG)} are not "
              "in the preregistration")
        for r, p in stray[:5]:
            print(f"  {str(r)[:38]} -> {str(p)[:38]}")
        print("Derive the task with scripts/eval/make_task.py rather than editing it.")
        return 2
    print(f"  task: {task_blob.get('task')} from {task_blob.get('source')}")
    print(f"  all {len(steps)} step(s) are preregistered")

    print(f"\n== running {len(steps)} step(s), cap {a.cap_core_h} core-hours ==")
    env = os.environ.copy()
    env["CHEM_ASSET_SET"] = a.name          # pin the set inside the arm
    # Read by scripts/reflect/asset_snapshot.py, which refuses to bump while it is set. Prevention
    # as well as the detection above: this was previously set and read by nothing, which made
    # "Reflect is closed" a claim resting only on the arm never calling Reflect.
    env["CHEM_REFLECT_CLOSED"] = "1"
    results = []
    t0 = time.time()
    for i, step in enumerate(steps, 1):
        spent = spent_core_h(dest)
        if spent >= a.cap_core_h:
            print(f"  cap reached after {i - 1} step(s): {spent} core-hours")
            break
        r, p = step["reactant"], step["product"]
        print(f"  step {i}/{len(steps)}  {r[:30]} -> {p[:30]}   (spent {spent})")
        cmd = [
            sys.executable, os.path.join(dest, "loop", "skill_runner.py"),
            "--reactant-smiles", r, "--product-smiles", p,
            "--workdir", os.path.join(dest, "runs", f"step_{i}"),
            "--nprocs", str(a.nprocs), "--wall-s", str(a.wall_s),
            # Pinned rather than defaulted: the guess budget has to be identical across arms, and a
            # default that changed between runs would make the arms differ in more than the assets.
            "--max-rounds", str(a.max_rounds),
            "--budget-core-h", str(a.cap_core_h - spent),
        ]
        if step.get("coproduct"):
            cmd += ["--coproduct", step["coproduct"]]
        out = sh(cmd, cwd=dest, env=env)
        results.append({
            "step": i, "reactant": r, "product": p,
            "rc": out.returncode,
            "tail": (out.stdout or out.stderr or "")[-400:],
        })

    n_after, d_after = ledger_digest()
    na_after, da_after = asset_digest(dest)
    ledger_unchanged = (n_after, d_after) == (n_before, d_before)
    assets_unchanged = (na_after, da_after) == (na_before, da_before)
    # Both must hold. The ledger catches a revision landing through the bump path; the asset digest
    # catches an arm editing its own skill directly, which the skills' write/edit tools allow and
    # which the ledger would not show.
    reflect_closed = ledger_unchanged and assets_unchanged
    report = {
        "asset_set": a.name,
        "cap_core_h": a.cap_core_h,
        "max_rounds": a.max_rounds,
        "spent_core_h": spent_core_h(dest),
        "wall_s": round(time.time() - t0),
        "steps_attempted": len(results),
        "steps_total": len(steps),
        "reflect_closed": reflect_closed,
        "ledger_unchanged": ledger_unchanged,
        "assets_unchanged": assets_unchanged,
        "ledger_before": {"n": n_before, "digest": d_before},
        "ledger_after": {"n": n_after, "digest": d_after},
        "assets_before": {"n": na_before, "digest": da_before},
        "assets_after": {"n": na_after, "digest": da_after},
        "task": os.path.relpath(a.task, PKG) if a.task else None,
        "results": results,
    }
    out_path = os.path.join(dest, "ARM_REPORT.json")
    json.dump(report, open(out_path, "w"), indent=2)
    print(f"\n== arm {a.name} ==")
    print(f"  spent {report['spent_core_h']} of {a.cap_core_h} core-hours")
    print(f"  reflect closed: {reflect_closed}")
    if not ledger_unchanged:
        print(f"  ARM VOID: a revision landed during evaluation "
              f"({n_before} -> {n_after} entries)")
    if not assets_unchanged:
        print("  ARM VOID: an asset changed while the arm ran, without going through the ledger")
    print(f"  report: {os.path.relpath(out_path, PKG)}")
    return 0 if reflect_closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
