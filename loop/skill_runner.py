#!/usr/bin/env python3
"""Validate one elementary step via pi-driven generate/diagnose rounds + run_qm_step.

Mirrors TSBench run_iterative_skill_loop structure, but launches project-local pi
and the QM driver in tools/workflow/run_qm_step.py.

Usage:
  python loop/skill_runner.py \\
    --reactant-smiles "..." --product-smiles "..." \\
    [--coproduct O] --workdir runs/validation/<id> [--max-rounds 3]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "scripts" / "lib"))
sys.path.insert(0, str(PKG / "scripts" / "validate"))
import chem_paths as CP  # noqa: E402
import verdict_writer as _VW  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asset_set as _AS  # noqa: E402

CP.bootstrap()


def _run_qm_step_label(root: Path | None = None) -> str:
    """Driver tag from the tree that is actually running, not a hardcoded live version.

    A C2 arm materialises assets/initial or assets/final (run_qm_step v0) and
    launches this file from that tree. Writing run_qm_step.v1 there contradicts
    the arm's VERSIONS.json.
    """
    roots: list[Path] = []
    if root is not None:
        roots.append(Path(root))
    cwd = Path.cwd()
    if cwd not in roots:
        roots.append(cwd)
    if PKG not in roots:
        roots.append(PKG)
    for r in roots:
        vf = r / "tools" / "VERSIONS.json"
        if not vf.is_file():
            continue
        try:
            v = (json.load(open(vf)).get("tools") or {}).get("workflow/run_qm_step.py")
        except (OSError, json.JSONDecodeError):
            continue
        if not v:
            continue
        s = str(v)
        if not s.startswith("v"):
            s = "v" + s
        return f"run_qm_step.{s}"
    return "run_qm_step.v0"


# ORCA scratch that is worthless once a step has been adjudicated or abandoned.
SCRATCH_GLOBS = (
    "*.gbw",
    "*.densities*",
    "*.tmp",
    "*.tmp.*",
    "*.bas?",
    "*.cpcm*",
    "*.hostnames",
    "*.bibtex",
    "*.carthess",
    "*.citations.tmp",
    "*.E.tmp",
    "*.en.tmp",
    "*.EIJ.tmp",
)


def _cleanup_scratch(workdir: Path, name: str | None = None) -> int:
    """Delete ORCA scratch left by a killed or early-exited run. Keeps .out/.xyz/.hess."""
    prefix = f"{name}*" if name else "*"
    removed = 0
    for pat in SCRATCH_GLOBS:
        for f in glob.glob(str(workdir / (prefix + pat.lstrip("*")))):
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
    return removed

SCHEMA_VERSION = "reaxevolve_ts_search.v1"


def run(cmd, cwd=None, env=None, timeout=None):
    return subprocess.run(
        cmd,
        cwd=cwd or str(PKG),
        env=env or os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def run_group(cmd, cwd=None, env=None, timeout=None):
    """Run in its own process group so a wall-clock kill also takes down ORCA/MPI children.

    subprocess.run(timeout=) only kills the direct child; ORCA keeps burning cores.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd or str(PKG),
        env=env or os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                out, err = proc.communicate(timeout=15)
                return proc.returncode, out, err, True
            except subprocess.TimeoutExpired:
                continue
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return proc.returncode, out, err, True


def ensure_reactant_xyz(smiles: str, path: Path) -> Path:
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    r = run(
        [
            CP.PYBIN,
            str(PKG / "tools" / "geometry" / "smi_to_xyz.py"),
            smiles,
            str(path),
        ]
    )
    if r.returncode != 0 or not path.is_file():
        raise RuntimeError(f"smi_to_xyz failed: {r.stderr or r.stdout}")
    return path


def map_atoms(
    reactant: str, product: str, out: Path, coproduct: str | None = None
) -> dict:
    # Dehydration etc. change heavy-atom count on the organic product alone;
    # map against product(+coproduct) so compositions match (e.g. ".O" for water).
    product_side = product if not coproduct else f"{product}.{coproduct}"
    r = run(
        [
            CP.PYBIN,
            str(PKG / "tools" / "geometry" / "map_reaction_atoms.py"),
            reactant,
            product_side,
            "--json-out",
            str(out),
        ]
    )
    if out.is_file():
        data = json.load(open(out))
    else:
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return {"raw_stdout": r.stdout, "stderr": r.stderr, "rc": r.returncode}
    # Tool may write a ranked list; skills expect one mapping record.
    if isinstance(data, list):
        data = data[0] if data else {}
    if isinstance(data, dict):
        data["product_side_smiles"] = product_side
        data["coproduct"] = coproduct
        # Keep a single-object JSON on disk for skill readers.
        json.dump(data, open(out, "w"), indent=2)
        open(out, "a").write("\n")
    return data


def pi_skill(skill_dirs, prompt: str, tools: str = "read,bash,write,edit") -> str:
    """Run one pi call with the given skills loaded.

    Takes a list because a role can be filled by more than one skill: the two initial-set skills
    both merged into the final set's ts-validation-strategy, and failure diagnosis there is split
    across it and strict-edge-criterion. A single-skill signature would have forced the caller to
    pick one half of a recorded merge.
    """
    if isinstance(skill_dirs, (str, Path)):
        skill_dirs = [skill_dirs]
    if not skill_dirs:
        raise RuntimeError("pi_skill called with no skills: the prompt would name an unloaded skill")
    env = os.environ.copy()
    env["SKILL_FLAGS"] = " ".join(f"--skill {d}" for d in skill_dirs)
    env["TOOL_FLAGS"] = f"--tools {tools}"
    r = run([str(PKG / "loop" / "pi_call.sh"), prompt], env=env, timeout=3600)
    out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    if r.returncode != 0:
        raise RuntimeError(f"pi skill failed rc={r.returncode}: {out[-2000:]}")
    return out


def init_record(path: Path, reaction_id: str, mapping: dict, round_idx: int = 0):
    if path.is_file():
        rec = json.load(open(path))
    else:
        rec = []
    while len(rec) <= round_idx:
        rec.append(
            {
                "schema": SCHEMA_VERSION,
                "reaction_id": reaction_id,
                "round": len(rec),
                "generation_policy": {},
                "guesses": [],
                "diagnosis_feedback": [],
                "reaction_mapping": mapping,
            }
        )
    json.dump(rec, open(path, "w"), indent=2)
    open(path, "a").write("\n")
    return rec


def list_guess_xyz(round_dir: Path) -> list[Path]:
    """Final guess geometries only — never builder intermediates (*_tmp*)."""
    if not round_dir.is_dir():
        return []
    found = list(round_dir.glob("*.xyz")) + list(round_dir.glob("guesses/*.xyz"))
    seen: set[str] = set()
    out: list[Path] = []
    for p in sorted(found):
        if "_tmp" in p.name:
            continue
        if p.name.endswith("_guess.xyz"):
            continue
        s = str(p.resolve())
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def guesses_from_record(record_path: Path, workdir: Path, round_dir: Path) -> list[Path]:
    """Curated xyz paths from record.json (preferred over directory globs)."""
    out: list[Path] = []
    try:
        rec = json.load(open(record_path))
        for g in (rec[-1].get("guesses") or []):
            xp = g.get("xyz_path")
            if not xp:
                continue
            for cand in (Path(xp), workdir / xp, round_dir / xp, round_dir / Path(xp).name,
                         round_dir / "guesses" / Path(xp).name):
                if cand.is_file() and "_tmp" not in cand.name:
                    out.append(cand)
                    break
    except Exception:
        pass
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        s = str(p.resolve())
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def _invocation_id() -> str | None:
    return os.environ.get("CHEM_INVOCATION_ID") or None


def _stamp_cost(cache_path: str, edge_key: str, wall_s: float, nprocs: int) -> None:
    """Write wall_s/nprocs onto the cache record the arm budget later sums.

    write_strict_cache persists whatever is in the record at write time. The
    success path is written by run_qm_step, which does not know the outer
    elapsed wall. Setting wall_s only on the in-memory return left completed
    jobs at 0 core-hours when arm_runner.spent_core_h read the cache.
    """
    try:
        data = json.load(open(cache_path))
    except (OSError, json.JSONDecodeError):
        return
    rec = data.get(edge_key)
    if not isinstance(rec, dict):
        return
    rec["wall_s"] = float(wall_s)
    rec["nprocs"] = int(nprocs)
    inv = _invocation_id()
    if inv:
        rec["invocation_id"] = inv
    atts = rec.get("attempts")
    if isinstance(atts, list) and atts and isinstance(atts[-1], dict):
        atts[-1]["wall_s"] = float(wall_s)
        atts[-1]["nprocs"] = int(nprocs)
        if inv:
            atts[-1]["invocation_id"] = inv
    json.dump(data, open(cache_path, "w"), indent=2)
    open(cache_path, "a").write("\n")


def _harvest_perceived(res: dict, dest: Path | None = None) -> None:
    """Record IRC termini that are not the proposed pair.

    They are candidates, not verdicts. Explore still has to submit them through
    add_hypothesis before Validate will spend QM on them.
    """
    if res.get("status") == "STRICT" or res.get("policy_pass"):
        return
    if res.get("endpoint_double_ended"):
        return
    em = res.get("endpoint_match") if isinstance(res.get("endpoint_match"), dict) else {}
    if (em.get("F_isReactant") and em.get("B_isProduct")) or (
        em.get("F_isProduct") and em.get("B_isReactant")
    ):
        return
    fwd = res.get("irc_fwd") or res.get("fwd")
    bwd = res.get("irc_bwd") or res.get("bwd")
    if not fwd or not bwd or fwd == bwd:
        return
    proposed = {res.get("reactant"), res.get("product"), res.get("coproduct")} - {None, ""}
    perceived = set()
    for side in (fwd, bwd):
        perceived.update(x for x in str(side).split(".") if x)
    if perceived and perceived <= proposed:
        return
    dest = dest or (PKG / "graph" / "caches" / "discovered_cache.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if dest.is_file():
        try:
            blob = json.loads(dest.read_text())
            rows = blob if isinstance(blob, list) else blob.get("edges") or []
        except json.JSONDecodeError:
            rows = []
    key = f"{fwd}>>{bwd}"
    if any(r.get("edge") == key for r in rows if isinstance(r, dict)):
        return
    rows.append(
        {
            "edge": key,
            "reactant": fwd,
            "product": bwd,
            "source": "irc_harvest",
            "parent": f"{res.get('reactant')}>>{res.get('product')}",
            "status": res.get("status"),
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    dest.write_text(json.dumps(rows, indent=2) + "\n")


def validate_guess(
    name: str,
    guess: Path,
    reactant: str,
    product: str,
    coproduct: str | None,
    workdir: Path,
    nprocs: int,
    wall_s: int,
) -> dict:
    # run_qm_step chdir()s into --workdir, so every path handed to it must be absolute:
    # a repo-relative guess path silently fails to open once the driver has moved.
    workdir = workdir.resolve()
    guess = Path(guess).resolve()
    cmd = [
        CP.PYBIN,
        str(PKG / "tools" / "workflow" / "run_qm_step.py"),
        "--name",
        name,
        "--guess",
        str(guess),
        "--reactant",
        reactant,
        "--product",
        product,
        "--workdir",
        str(workdir),
        "--nprocs",
        str(nprocs),
    ]
    if coproduct:
        cmd += ["--coproduct", coproduct]
    t0 = time.time()
    rc, out, err, timed_out = run_group(cmd, cwd=str(workdir), timeout=wall_s)
    elapsed = time.time() - t0

    if timed_out:
        # The driver was killed before it could adjudicate, so no verdict exists for
        # this attempt. Record it here (code path, not an LLM) or the failure vanishes.
        res = {
            "name": name,
            "reactant": reactant,
            "product": product,
            "coproduct": coproduct,
            "driver": _run_qm_step_label(),
            "guess_path": str(guess),
            "wall_s": elapsed,
            "nprocs": nprocs,
            "invocation_id": _invocation_id(),
        }
        written = _VW.write_strict_cache(
            str(workdir / "strict_cache.json"),
            f"{reactant}>>{product}",
            res,
            "unresolved",
            f"WALL_TIME>{wall_s}s",
        )
        _cleanup_scratch(workdir, name)
        written["wall_s"] = elapsed
        written["guess_path"] = str(guess)
        written["nprocs"] = nprocs
        return written

    try:
        res = json.loads(out) if (out or "").strip() else {}
    except json.JSONDecodeError:
        try:
            res = json.loads((out or "").strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            res = {}

    if not res.get("status"):
        # Driver crashed, produced nothing parseable, or exited before adjudicating.
        # Never return a status-less result: that would look like "nothing happened".
        detail = f"DRIVER_NO_VERDICT rc={rc}"
        tail = ((err or "") + (out or "")).strip()[-400:]
        if tail:
            detail += f" :: {tail}"
        res = _VW.write_strict_cache(
            str(workdir / "strict_cache.json"),
            f"{reactant}>>{product}",
            {
                "name": name,
                "reactant": reactant,
                "product": product,
                "coproduct": coproduct,
                "driver": _run_qm_step_label(),
                "rc": rc,
                "wall_s": elapsed,
                "nprocs": nprocs,
                "invocation_id": _invocation_id(),
                "stdout_tail": (out or "")[-1500:],
                "stderr_tail": (err or "")[-1500:],
            },
            "unresolved",
            detail,
        )
        _cleanup_scratch(workdir, name)

    res["wall_s"] = elapsed
    res["nprocs"] = nprocs
    res["guess_path"] = str(guess)
    _stamp_cost(str(workdir / "strict_cache.json"), f"{reactant}>>{product}", elapsed, nprocs)
    _harvest_perceived(res)
    return res


def budget_wall_cap(
    wall_s: int,
    nprocs: int,
    budget_core_h: float | None,
    spent_core_h: float,
    min_useful_s: int = 300,
) -> int | None:
    """Wall seconds this guess may use, or None when the budget is spent.

    The campaign budget used to be checked only between loop rounds, so a single
    round could overshoot it by however long its guesses happened to run. Capping
    each guess by the remaining allowance makes the budget a hard bound.

    Returns None (do not launch) when the remainder would not buy a useful run —
    a 40-second OptTS just burns cores and produces another WALL_TIME verdict.
    """
    if budget_core_h is None:
        return int(wall_s)
    remaining_core_h = budget_core_h - spent_core_h
    if remaining_core_h <= 0:
        return None
    allowed_s = int(remaining_core_h * 3600.0 / max(1, nprocs))
    if allowed_s < min_useful_s:
        return None
    return min(int(wall_s), allowed_s)


def any_continuable(feedback: list) -> bool:
    if not feedback:
        return True
    for fb in feedback:
        if not isinstance(fb, dict):
            continue
        if fb.get("if_need_new_mechanism"):
            return True
        if fb.get("branch_decision") != "stop_this_branch":
            return True
    return False


def run_step(
    reactant: str,
    product: str,
    workdir: Path,
    coproduct: str | None = None,
    max_rounds: int = 3,
    nprocs: int = 16,
    wall_s: int = 5400,
    reactant_xyz: Path | None = None,
    budget_core_h: float | None = None,
) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    reaction_id = workdir.name or uuid.uuid4().hex[:10]
    r_xyz = ensure_reactant_xyz(reactant, reactant_xyz or (workdir / "R.xyz"))
    mapping_path = workdir / "reaction_mapping.json"
    mapping = map_atoms(reactant, product, mapping_path, coproduct=coproduct)
    record_path = workdir / "record.json"

    # Resolve skills by role, not by name. These were two hardcoded initial-set names, which meant
    # this runner could not execute against the final asset set — the set the live tree carries —
    # because those skills do not exist under those names there. CHEM_ASSET_SET lets a caller pin
    # the set; by default it is whichever set this tree declares.
    asset_set = os.environ.get("CHEM_ASSET_SET") or _AS.live_set_name()
    gen_skills = [Path(d) for d in _AS.skill_dirs(asset_set, "guess_generation")]
    diag_skills = [Path(d) for d in _AS.skill_dirs(asset_set, "failure_diagnosis")]

    history = []
    best = None
    spent_core_h = 0.0
    stop_reason = None
    # Hard cap: one elementary step must not enqueue every builder intermediate.
    max_guesses_per_round = 3

    for rnd in range(max_rounds):
        round_dir = workdir / f"round_{rnd}"
        round_dir.mkdir(exist_ok=True)
        init_record(record_path, reaction_id, mapping, rnd)

        gen_names = ", ".join(p.name for p in gen_skills)
        gen_prompt = f"""Use these loaded skills for exactly one round: {gen_names}.

Round: {rnd}
Reaction ID: {reaction_id}
Record JSON: {record_path}
Workdir: {workdir}
Round dir: {round_dir}
Reactant SMILES: {reactant}
Product SMILES: {product}
Reactant XYZ: {r_xyz}
Coproduct: {coproduct}

Reaction mapping (may be partial):
```json
{json.dumps(mapping, indent=2)[:8000]}
```

Requirements:
- Read `{record_path}` as a JSON array; last element is the current round.
- Write guesses fragment to `{round_dir}/guesses.record_update.json`.
- Run: python tools/record_update.py set-guesses --record {record_path} --json-file {round_dir}/guesses.record_update.json
- Keep all xyz under `{round_dir}`.
- Final guess files only (no `*_tmp*.xyz` intermediates) — at most {max_guesses_per_round}.
- Do not edit policy/ or leave the reaxevolve workspace.
"""
        try:
            pi_skill(gen_skills, gen_prompt)
        except Exception as e:
            history.append({"round": rnd, "results": [], "gen_error": str(e)})
            stop_reason = "generator_error"
            break

        # Prefer the curated record list; fall back to non-tmp xyz on disk.
        guesses = guesses_from_record(record_path, workdir, round_dir)
        if not guesses:
            guesses = list_guess_xyz(round_dir)
        if len(guesses) > max_guesses_per_round:
            print(
                f"[skill_runner] truncating {len(guesses)} guesses → "
                f"{max_guesses_per_round}",
                file=sys.stderr,
            )
            guesses = guesses[:max_guesses_per_round]

        round_results = []
        for i, gpath in enumerate(guesses):
            allowed_s = budget_wall_cap(wall_s, nprocs, budget_core_h, spent_core_h)
            if allowed_s is None:
                stop_reason = "budget_exhausted"
                print(
                    f"[skill_runner] core-hour budget spent "
                    f"({spent_core_h:.2f}/{budget_core_h:.2f}) — skipping remaining "
                    f"{len(guesses) - i} guess(es)",
                    file=sys.stderr,
                )
                break

            name = f"r{rnd}_g{i}"
            # copy guess into workdir root for ORCA relative paths
            local = workdir / f"{name}_guess.xyz"
            if Path(gpath).resolve() != local.resolve():
                shutil.copy2(gpath, local)
            res = validate_guess(
                name, local, reactant, product, coproduct, workdir, nprocs, allowed_s
            )
            spent_core_h += nprocs * float(res.get("wall_s") or 0) / 3600.0
            res["budget_core_h_spent"] = round(spent_core_h, 4)
            round_results.append(res)
            st = res.get("status")
            if best is None or (st == "STRICT") or (
                best.get("status") != "STRICT" and st == "evidence_ok"
            ):
                best = res
            if st == "STRICT":
                break

        if stop_reason == "budget_exhausted":
            history.append({"round": rnd, "results": round_results, "stop": stop_reason})
            break

        # attach validation into record guesses if possible
        try:
            rec = json.load(open(record_path))
            for g, res in zip(rec[-1].get("guesses") or [], round_results):
                g["validation"] = {
                    "status": res.get("status"),
                    "detail": res.get("detail"),
                    "ts_imag_cm-1": res.get("ts_imag_cm-1"),
                    "endpoint_match": res.get("endpoint_match"),
                }
            json.dump(rec, open(record_path, "w"), indent=2)
        except Exception:
            pass

        if best and best.get("status") == "STRICT":
            history.append({"round": rnd, "results": round_results, "stop": "STRICT"})
            break

        diag_names = ", ".join(p.name for p in diag_skills)
        diag_prompt = f"""Use these loaded skills for exactly one round: {diag_names}.

Round: {rnd}
Record JSON: {record_path}
Workdir: {workdir}
Round dir: {round_dir}

Requirements:
- Diagnose current round guesses using validation fields and ORCA outs in workdir.
- Write `{round_dir}/diagnosis_feedback.record_update.json`.
- Run: python tools/record_update.py set-diagnosis-feedback --record {record_path} --json-file {round_dir}/diagnosis_feedback.record_update.json
- Do not leave reaxevolve workspace.
"""
        try:
            pi_skill(diag_skills, diag_prompt)
        except Exception as e:
            history.append({"round": rnd, "results": round_results, "diag_error": str(e)})
            break

        try:
            rec = json.load(open(record_path))
            fb = rec[-1].get("diagnosis_feedback") or []
        except Exception:
            fb = []
        history.append({"round": rnd, "results": round_results, "feedback_n": len(fb)})
        if not any_continuable(fb):
            break

    out = {
        "reaction_id": reaction_id,
        "reactant": reactant,
        "product": product,
        "coproduct": coproduct,
        "workdir": str(workdir),
        "best": best,
        "history": history,
        "status": (best or {}).get("status") or "unresolved",
        "core_hours_spent": round(spent_core_h, 4),
        "budget_core_h": budget_core_h,
        "stop_reason": stop_reason,
        "invocation_id": _invocation_id(),
    }
    json.dump(out, open(workdir / "skill_runner_result.json", "w"), indent=2)
    return out


def load_result_if_this_run(
    saved: Path,
    invocation_id: str | None = None,
    started: float | None = None,
) -> dict:
    """Only a result this invocation wrote is this launch's verdict."""
    del started
    if not saved.is_file() or not invocation_id:
        return {}
    try:
        loaded = json.load(open(saved))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(loaded, dict) and loaded.get("invocation_id") == invocation_id:
        return loaded
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reactant-smiles", required=True)
    ap.add_argument("--product-smiles", required=True)
    ap.add_argument("--coproduct", default=None)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--reactant-xyz", default=None)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--nprocs", type=int, default=16)
    ap.add_argument("--wall-s", type=int, default=5400)
    ap.add_argument(
        "--budget-core-h",
        type=float,
        default=None,
        help="core-hours this step may spend; caps each guess so one round "
        "cannot overshoot the campaign budget. Omit for no intra-step limit.",
    )
    ap.add_argument(
        "--invocation-id",
        default=None,
        help="caller-assigned id for this launch; reused workdirs must not "
        "inherit a previous result or its core-hours",
    )
    a = ap.parse_args()
    wd = Path(a.workdir)
    invocation_id = a.invocation_id or uuid.uuid4().hex
    os.environ["CHEM_INVOCATION_ID"] = invocation_id
    try:
        res = run_step(
            a.reactant_smiles,
            a.product_smiles,
            wd,
            coproduct=a.coproduct,
            max_rounds=a.max_rounds,
            nprocs=a.nprocs,
            wall_s=a.wall_s,
            reactant_xyz=Path(a.reactant_xyz) if a.reactant_xyz else None,
            budget_core_h=a.budget_core_h,
        )
    except Exception as exc:
        saved = wd / "skill_runner_result.json"
        res = load_result_if_this_run(saved, invocation_id)
        if not res:
            res = {
                "status": "unresolved",
                "history": [],
                "core_hours_spent": 0.0,
                "invocation_id": invocation_id,
            }
        res.setdefault("status", "unresolved")
        res["error"] = str(exc)[:1000]
        res.setdefault("history", [])
        res.setdefault("core_hours_spent", 0.0)
        json.dump(res, open(saved, "w"), indent=2)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("status") in ("STRICT", "evidence_ok", "rejected", "unresolved") else 1


if __name__ == "__main__":
    raise SystemExit(main())
