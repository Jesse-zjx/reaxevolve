#!/usr/bin/env python3
"""Stage-1 Reflect: emit a rich bundle for humans / fully_auto without mutating assets."""
from __future__ import annotations

import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
PY = os.environ.get("CHEM_PYTHON") or os.environ.get("CHEM_PY") or "python3"


def _load_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.load(open(path))
    except Exception:
        return default


def _failure_digest(limit_kinds: int = 8) -> dict:
    """Run scripts/reflect/failure_digest.py (no unsupported --limit flag)."""
    script = PKG / "scripts" / "reflect" / "failure_digest.py"
    if not script.is_file():
        return {"error": "failure_digest.py missing"}
    r = subprocess.run(
        [PY, str(script), "--examples", "2"],
        cwd=str(PKG),
        text=True,
        capture_output=True,
    )
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout or "")[-1500:], "rc": r.returncode}
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": "unparseable failure_digest stdout", "tail": (r.stdout or "")[-1500:]}
    # Keep the bundle small for the LLM context window.
    by_kind = data.get("by_kind") or {}
    ranked = sorted(by_kind.items(), key=lambda kv: -int((kv[1] or {}).get("attempts") or 0))
    data["by_kind"] = {k: v for k, v in ranked[:limit_kinds]}
    return data


def _queue_summary() -> dict:
    qpath = PKG / "graph" / "caches" / "candidate_queue.json"
    data = _load_json(qpath, {}) or {}
    cands = data.get("candidates") or []
    status = Counter(c.get("status") or "pending" for c in cands)
    pending = [c for c in cands if c.get("status") in (None, "pending", "proposed")]
    pending = sorted(pending, key=lambda c: -float(c.get("priority") or 0))
    top = [
        {
            "kind": c.get("kind"),
            "priority": c.get("priority"),
            "edge_id": c.get("edge_id"),
            "reactant": c.get("reactant"),
            "product": c.get("product"),
            "attempts": c.get("attempts") or 0,
        }
        for c in pending[:8]
    ]
    kind_counts = Counter(c.get("kind") or "unknown" for c in pending)
    return {
        "n": len(cands),
        "status_counts": dict(status),
        "pending_kind_counts": dict(kind_counts),
        "top_pending": top,
    }


def _recent_metrics(n: int = 8) -> list:
    path = PKG / "evidence" / "state" / "loop" / "loop_metrics.jsonl"
    if not path.is_file():
        return []
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _edge_status_counts(net: dict) -> dict:
    edges = list((net.get("edges") or {}).values())
    return dict(Counter(e.get("status") or "unknown" for e in edges))


def _reflect_pressure(n_strict: int, reachable: bool, evo_n: int, metrics: list, digest: dict) -> dict:
    """Tell fully_auto when noop is unacceptable."""
    reasons = []
    if n_strict < 2:
        reasons.append(f"n_strict={n_strict} (<2); need more STRICT edges toward HMF")
    if not reachable:
        reasons.append("target_reachable_strict_from_glucose is false")
    if evo_n == 0:
        reasons.append("EVOLUTION_LOG is empty — no asset revision yet this campaign")
    recent = metrics[-3:] if metrics else []
    if recent and all(int(m.get("d_strict") or 0) == 0 and int(m.get("d_evo") or 0) == 0 for m in recent):
        reasons.append("last ≤3 metrics rows show d_strict=0 and d_evo=0 (idle risk)")
    totals = (digest or {}).get("totals") or {}
    attempts = int(totals.get("attempts") or 0)
    passed = int(totals.get("passed") or 0)
    if attempts >= 3 and passed <= 1:
        reasons.append(f"failure_digest attempts={attempts} passed={passed}")
    # Soft: if digest has a dominant failure, name it.
    by_kind = (digest or {}).get("by_kind") or {}
    dominant = []
    for kind, g in by_kind.items():
        df = (g or {}).get("dominant_failure")
        if df and df != "ok":
            dominant.append(f"{kind}:{df}")
    if dominant:
        reasons.append("dominant failures: " + ", ".join(dominant[:6]))
    must = False
    if not reachable:
        # Still short of the campaign goal → keep pressing for revisions when
        # we have little STRICT, no evo yet, or recent idle metrics.
        if evo_n == 0 or n_strict < 2:
            must = True
        elif recent and all(
            int(m.get("d_strict") or 0) == 0 and int(m.get("d_evo") or 0) == 0 for m in recent
        ):
            must = True
        elif attempts >= 5 and passed <= max(1, n_strict):
            must = True
    return {"must_revise": must, "reasons": reasons}


def run(bundle_path: str | None = None) -> dict:
    net_path = PKG / "graph" / "canonical" / "reaction_network.json"
    net = _load_json(net_path, {}) or {}
    meta = net.get("meta") or {}
    n_strict = sum(1 for e in (net.get("edges") or {}).values() if e.get("status") == "STRICT")
    reachable = bool(meta.get("target_reachable_strict_from_glucose"))

    core_h = 0.0
    ch = PKG / "evidence" / "state" / "loop" / "core_hours.json"
    blob = _load_json(ch, {}) or {}
    try:
        core_h = float(blob.get("core_hours") or 0)
    except Exception:
        pass

    evo = PKG / "evolution" / "EVOLUTION_LOG.jsonl"
    evo_n = sum(1 for line in open(evo) if line.strip()) if evo.is_file() else 0

    digest = _failure_digest()
    metrics = _recent_metrics()
    queue = _queue_summary()
    pressure = _reflect_pressure(n_strict, reachable, evo_n, metrics, digest)

    bundle = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": "reflect",
        "meta": {
            **meta,
            "n_nodes": len(net.get("nodes") or {}),
            "n_edges": len(net.get("edges") or {}),
            "n_strict": n_strict,
            "edge_status_counts": _edge_status_counts(net),
        },
        "n_strict": n_strict,
        "target_reachable": reachable,
        "core_hours": core_h,
        "evo_log_len": evo_n,
        "queue_summary": queue,
        "failure_digest": digest,
        "recent_metrics": metrics,
        "reflect_pressure": pressure,
        "whitelist": [".skills/", "tools/"],
        "policy_bar": "v5",
        "note": "genesis Reflect bundle v1 — rich digest for fully_auto",
    }
    out = Path(bundle_path or (PKG / "evidence" / "state" / "loop" / "reflect_bundle.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(bundle, open(out, "w"), indent=2)
    open(out, "a").write("\n")
    return bundle


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
