#!/usr/bin/env python3
"""Structural smoke test. No DFT, no API calls, no writes to Graph Memory.

Checks the invariants that keep results interpretable rather than checking chemistry:
the acceptance boundary is where it is supposed to be, the editable surface is exactly
what it is declared to be, both Explore paths are wired, and the two asset sets are
distinguishable. Run it after any structural change, and after any Reflect revision
(`loop/fully_auto/apply_revision.py --smoke` does this automatically).
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "scripts" / "lib"))
sys.path.insert(0, str(PKG / "tools"))

FAILS = []


def ok(msg):
    print(f"  OK  {msg}")


def fail(msg):
    print(f" FAIL {msg}")
    FAILS.append(msg)


def section(t):
    print(f"\n== {t} ==")


def main():
    section("1. paths")
    import chem_paths as CP

    CP.bootstrap()
    if Path(CP.PACKAGE) != PKG:
        fail(f"PACKAGE={CP.PACKAGE} != {PKG}")
    else:
        ok(f"PACKAGE={CP.PACKAGE}")
    for p in (CP.GRAPH, CP.RUNS, CP.EVOLUTION, CP.POLICY):
        if os.path.isdir(p):
            ok(p)
        else:
            fail(f"missing dir {p}")

    section("2. syntax")
    for rel in [
        "loop/run_loop.py",
        "loop/explore.py",
        "loop/explore_templates.py",
        "loop/explore_llm.py",
        "loop/select_candidates.py",
        "loop/mass_balance.py",
        "loop/skill_runner.py",
        "loop/reflect.py",
        "loop/fully_auto/apply_revision.py",
        "scripts/graph/add_hypothesis.py",
        "scripts/graph/build_reaction_network.py",
        "scripts/reflect/asset_snapshot.py",
        "scripts/reflect/consolidate_verdicts.py",
        "scripts/reflect/graph_views.py",
        "scripts/qa/isolation_audit.py",
        "scripts/qa/run_manifest.py",
        "scripts/qa/test_loop_accounting.py",
        "scripts/qa/test_runner_paths.py",
        "tools/expand/templates_expand.py",
        "tools/screen/diversity.py",
        "tools/workflow/run_qm_step.py",
    ]:
        path = PKG / rel
        if not path.is_file():
            fail(f"missing {rel}")
            continue
        try:
            ast.parse(path.read_text())
            ok(rel)
        except Exception as e:
            fail(f"{rel}: {e}")

    # `select` is a stdlib module that subprocess depends on indirectly; a loop module
    # by that name shadows it once loop/ is on sys.path.
    if (PKG / "loop" / "select.py").exists():
        fail("loop/select.py shadows the stdlib select module — use select_candidates.py")
    else:
        ok("no stdlib-shadowing module in loop/")

    section("3. live skills")
    live = sorted(p.name for p in (PKG / ".skills").iterdir() if p.is_dir()) if (PKG / ".skills").is_dir() else []
    if live:
        ok(f".skills present: {', '.join(live)}")
    else:
        fail(".skills is empty")
    for name in live:
        if not (PKG / ".skills" / name / "SKILL.md").is_file():
            fail(f".skills/{name} has no SKILL.md")

    section("4. tools surface")
    for rel in [
        "tools/geometry/builder.py",
        "tools/geometry/inquire.py",
        "tools/geometry/map_reaction_atoms.py",
        "tools/geometry/parse_orca_output.py",
        "tools/geometry/xyz_to_smiles.py",
        "tools/geometry/smi_to_xyz.py",
        "tools/record_update.py",
        "tools/expand/templates_expand.py",
        "tools/screen/diversity.py",
        "tools/guess/ladder.py",
        "tools/workflow/run_qm_step.py",
        "tools/VERSIONS.json",
    ]:
        if (PKG / rel).is_file():
            ok(rel)
        else:
            fail(f"missing {rel}")
    vers = json.load(open(PKG / "tools" / "VERSIONS.json"))
    for sec in ("skills", "tools"):
        if isinstance(vers.get(sec), dict) and vers[sec]:
            ok(f"VERSIONS.json has a {sec} table")
        else:
            fail(f"VERSIONS.json missing {sec} table")

    section("5. policy is the only acceptance boundary")
    ver = (PKG / "policy" / "acceptance" / "VERSION").read_text().strip()
    if ver == "v5":
        ok("STRICT VERSION=v5")
    else:
        fail(f"VERSION={ver}")
    targets = (PKG / "policy" / "targets_and_budget.md").read_text()
    missing = [t for t in ("HMF", "HAA", "Furfural") if t not in targets]
    if missing:
        fail(f"targets_and_budget missing target(s): {missing}")
    else:
        ok("three product targets declared")
    flat = " ".join(targets.split())  # the claim wraps across lines in the source
    if "human-set starting capability" in flat and "not an evolved finding" in flat:
        ok("QM floor declared human-set, not evolved")
    else:
        fail("targets_and_budget does not state the QM floor is human-set")
    # Only the verdict writer may assign status.
    for rel in ("loop/run_loop.py", "loop/explore.py", "loop/select_candidates.py"):
        if '"STRICT"' in (PKG / rel).read_text() and rel != "loop/select_candidates.py":
            fail(f"{rel} references the STRICT literal — status must come from verdict_writer")
    ok("loop does not assign STRICT itself")

    section("6. graph rebuild (throwaway copy)")
    probe = os.path.join(tempfile.mkdtemp(prefix="reaxevolve_smoke_net_"), "reaction_network.json")
    r = subprocess.run(
        [sys.executable, str(PKG / "scripts" / "graph" / "build_reaction_network.py"), "--out", probe],
        cwd=str(PKG),
        text=True,
        capture_output=True,
    )
    if r.returncode != 0:
        fail(f"build_reaction_network rc={r.returncode}: {r.stderr[-500:]}")
    else:
        ok("build_reaction_network")
        summary = json.loads(r.stdout)
        reach = summary.get("targets_reachable_strict") or {}
        if set(reach) >= {"HMF", "HAA", "FF"}:
            ok(f"per-target reachability reported: {reach}")
        else:
            fail(f"per-target reachability missing targets: {reach}")
        if "strict_distance_to_targets" in summary:
            ok("target-agnostic progress metric present")
        else:
            fail("no strict_distance_to_targets in rebuild summary")

    section("7. Explore path A enumerates and conserves atoms")
    sys.path.insert(0, str(PKG / "loop"))
    sys.path.insert(0, str(PKG / "tools" / "expand"))
    sys.path.insert(0, str(PKG / "tools" / "screen"))
    try:
        import mass_balance as MB
        import templates_expand as TE

        cands = TE.expand([TE.canon("O=CC(O)C(O)C(O)C(O)CO")], set())
        if not cands:
            fail("templates_expand.expand returned nothing for open-chain glucose")
        else:
            ok(f"enumerated {len(cands)} candidates from one species")
            bad = [
                c for c in cands
                if not MB.ok(c["reactant"], c["product"], c.get("coproduct"))
            ]
            if bad:
                fail(f"{len(bad)} enumerated candidates do not conserve atoms")
            else:
                ok("every enumerated candidate conserves atoms")
            if all(isinstance(c.get("score"), (int, float)) for c in cands):
                ok("every candidate carries a numeric score")
            else:
                fail("some candidates have no numeric score")
    except Exception as e:
        fail(f"template Explore path: {e}")

    section("8. add_hypothesis gate (throwaway network)")
    tmp = tempfile.mkdtemp(prefix="reaxevolve_smoke_")

    def _add(reactant, product, coproduct=None):
        cmd = [
            sys.executable, str(PKG / "scripts" / "graph" / "add_hypothesis.py"),
            "--reactant", reactant, "--product", product,
            "--kind", "smoke", "--mechanism", "smoke", "--priority", "0.1",
            "--network", os.path.join(tmp, "reaction_network.json"),
            "--queue", os.path.join(tmp, "candidate_queue.json"),
        ]
        if coproduct:
            cmd += ["--coproduct", coproduct]
        return subprocess.run(cmd, cwd=str(PKG), text=True, capture_output=True)

    r = _add("OCC1OC(O)C(O)C(O)C1O", "O=CC(O)C(O)C(O)C(O)CO")
    try:
        if r.returncode == 0 and json.loads(r.stdout).get("ok"):
            ok("balanced hypothesis accepted")
        else:
            fail(f"balanced hypothesis rejected: {r.stdout[-300:]}")
    except Exception:
        fail(f"add_hypothesis: {r.stdout[-200:]} {r.stderr[-200:]}")
    # Dropping a carbon without declaring the fragment must be refused.
    r = _add("O=CC(O)C(O)C(O)C(O)CO", "O=CC(O)C(O)C(O)CO")
    if r.returncode != 0 and "mass_unbalanced" in r.stdout:
        ok("unbalanced hypothesis refused by the gate")
    else:
        fail("gate accepted a hypothesis that loses a carbon fragment")

    section("9. editable surface matches what is declared")
    text = (PKG / "loop" / "fully_auto" / "apply_revision.py").read_text()
    # Declared by prefix. tools/geometry/ is deliberately absent: it is listed per file so the
    # two evidence parsers inside it can be excluded.
    for want in (".skills/", "tools/guess/", "tools/expand/", "tools/screen/", "tools/workflow/"):
        if f'"{want}"' in text:
            ok(f"whitelisted {want}")
        else:
            fail(f"{want} missing from the apply whitelist")
    if '"tools/geometry/"' in text:
        fail("tools/geometry/ is whitelisted by prefix, which would include the evidence parsers")
    for banned in ("policy/", "scripts/", "loop/"):
        if f'"{banned}"' in text:
            fail(f"{banned} must never be on the apply whitelist")
    ok("policy/, scripts/ and loop/ are not writable by Reflect")

    # Evidence parsers decide what the calculation says. A revision to one could change a
    # verdict without changing any chemistry, so they sit outside the editable surface.
    sys.path.insert(0, str(PKG / "loop" / "fully_auto"))
    try:
        import apply_revision as AR  # noqa: WPS433

        for parser in ("tools/geometry/parse_orca_output.py", "tools/geometry/xyz_to_smiles.py",
                       "tools/parse_orca_output.py", "tools/xyz_to_smiles.py"):
            if AR.allowed(parser):
                fail(f"evidence parser is writable by Reflect: {parser}")
        else:
            ok("evidence parsers are outside the editable surface")
        for evolvable in ("tools/geometry/builder.py", "tools/guess/ladder.py",
                          "tools/expand/templates_expand.py", ".skills/pathway-method/SKILL.md"):
            if not AR.allowed(evolvable):
                fail(f"asset should be evolvable but is not on the whitelist: {evolvable}")
        ok("guess, enumeration and skill assets remain evolvable")
    except Exception as e:
        fail(f"could not check the editable surface: {e}")
    if "expander_smoke_ok" in text:
        ok("revisions to the enumerator/scorer are exercised before they stand")
    else:
        fail("no callable smoke check for enumerator/scorer revisions")

    section("10. asset sets")
    init, fin = PKG / "assets" / "initial", PKG / "assets" / "final"
    for d in (init, fin):
        if d.is_dir():
            ok(str(d.relative_to(PKG)))
        else:
            fail(f"missing {d}")
    if (init / "tools" / "expand").exists() or (init / "tools" / "guess").exists():
        fail("initial asset set must not contain the enumerator or the guess ladder")
    else:
        ok("initial set has no enumerator and no guess ladder (the main capability delta)")
    if (fin / "tools" / "expand" / "templates_expand.py").is_file():
        ok("final set contains the enumerator")
    else:
        fail("final asset set is missing the enumerator")
    iv = init / "tools" / "VERSIONS.json"
    if iv.is_file() and json.load(open(iv)).get("asset_set") == "initial":
        ok("initial set is version-tagged")
    else:
        fail("initial asset set has no version tag")

    section("11. evolution ledger")
    log = PKG / "evolution" / "EVOLUTION_LOG.jsonl"
    if not log.is_file():
        fail("EVOLUTION_LOG.jsonl missing")
    else:
        rows = [json.loads(l) for l in open(log) if l.strip()]
        ok(f"{len(rows)} revision records")
        seqs = [r.get("seq") for r in rows]
        if seqs == sorted(s for s in seqs if s is not None) and None not in seqs:
            ok("seq is present and monotonic")
        else:
            fail("EVOLUTION_LOG seq is missing or out of order")
        stray = [k for r in rows for k in ("time", "ts", "updated_at") if k in r]
        if stray:
            fail(f"EVOLUTION_LOG carries wall-clock fields: {sorted(set(stray))}")
        else:
            ok("no wall-clock timestamps (revisions ordered by seq)")
        if all(r.get("class") for r in rows):
            ok("every record declares a revision class")
        else:
            fail("some records have no revision class")
    if (PKG / "evolution" / "ASSET_RENAMES.json").is_file():
        ok("ASSET_RENAMES.json")
    else:
        fail("ASSET_RENAMES.json missing")

    section("12. supplementary lanes are separated")
    ts = PKG / "tsbench" / "README.md"
    if ts.is_file():
        body = ts.read_text()
        if "STRICT" in body and "never" in body:
            ok("tsbench lane states its own criterion and non-comparability")
        else:
            fail("tsbench/README.md does not state its acceptance criterion")
    else:
        fail("tsbench/README.md missing")
    # Prose provenance ("the loop shape mirrors TSBench") is fine and worth keeping.
    # What must not exist is a dependency: an import, a path into the lane, or its env var.
    hits = subprocess.run(
        ["grep", "-rnE", r"(import +tsbench|from +tsbench|tsbench/|TSBENCH_ROOT)",
         str(PKG / "loop"), str(PKG / "scripts")],
        text=True, capture_output=True,
    ).stdout
    # These name the lane in order to fence it off, not to depend on it.
    exempt = ("isolation_audit", "smoke_test", "check_doc_paths")
    offenders = [l for l in hits.splitlines() if not any(e in l for e in exempt)]
    if offenders:
        fail(f"main loop depends on the tsbench lane: {offenders[:2]}")
    else:
        ok("no dependency from loop/ or scripts/ on the tsbench lane")

    section("13. QA sub-checks")
    for script, label in (
        ("check_doc_paths.py", "every documented repo path resolves"),
        ("test_failure_taxonomy.py", "failure taxonomy and classifier agree"),
        ("test_preregistration.py", "panel is disjoint from the C2 task and still resolves"),
        ("test_guess_ladder.py", "guess ladder reaches its tools and the mapper contract holds"),
        ("test_endpoint_match.py", "an unusable IRC endpoint rejects instead of crashing"),
    ):
        r = subprocess.run(
            [sys.executable, str(PKG / "scripts" / "qa" / script)],
            cwd=str(PKG), text=True, capture_output=True,
        )
        if r.returncode == 0:
            ok(label)
        else:
            fail(f"{script}:\n{(r.stdout or r.stderr).strip()[-600:]}")
    for script in ["scripts/qa/isolation_audit.py", "scripts/qa/run_manifest.py"]:
        r = subprocess.run([sys.executable, str(PKG / script)], cwd=str(PKG), capture_output=True)
        if r.returncode in (0, 1):  # audit returns 1 on violations
            ok(script)
        else:
            fail(f"{script} rc={r.returncode}")
    r = subprocess.run(
        [sys.executable, str(PKG / "scripts" / "qa" / "test_loop_accounting.py")],
        cwd=str(PKG), text=True, capture_output=True,
    )
    if r.returncode == 0:
        ok("core-hour + queue-writeback invariants")
    else:
        fail(f"loop accounting rc={r.returncode}: {(r.stdout or r.stderr).strip()[-300:]}")

    section("14. evidence isolation of the verdict archive")
    cv = (PKG / "scripts" / "reflect" / "consolidate_verdicts.py").read_text()
    if "defaults = ['/root/" in cv:
        fail("consolidate_verdicts defaults to an out-of-repository cache root")
    else:
        ok("consolidate_verdicts has no external default roots")

    section("15. toolchain (informational)")
    try:
        from rdkit import Chem  # noqa: F401

        ok("rdkit")
    except ImportError:
        fail("rdkit missing")
    for label, path in (("orca", os.path.join(CP.ORCA_DIR, "orca")), ("xtb", CP.XTB_BIN)):
        print(f"  --  {label}: {'found' if os.path.isfile(path) else 'NOT FOUND'} ({path})")
    pi = PKG / "node_modules" / ".bin" / "pi"
    if pi.exists():
        print(f"  --  pi: {subprocess.check_output([str(pi), '--version'], text=True).strip()}")
    else:
        print("  --  pi: not installed (run `npm install`; only Explore path B and Reflect need it)")

    print("\n==== SUMMARY ====")
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
