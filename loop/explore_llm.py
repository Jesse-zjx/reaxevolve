#!/usr/bin/env python3
"""Explore path B — ask project-local pi (no tools) for the steps templates cannot express.

Runs after `loop/explore_templates.py` and is given that stage's coverage report, so it
is asked for the complement of the deterministic enumeration rather than for more of the
same. Every proposal lands through `scripts/graph/add_hypothesis.py`, which enforces
atom conservation; unbalanced proposals are handed their exact atom deficit and the
formula the product must have, and get two repair attempts before being dropped.

Usage:
  python loop/explore_llm.py [--top 4] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PKG, "scripts", "lib"))
import chem_paths as CP  # noqa: E402

CP.bootstrap()

GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"
GLUCOSE_OPEN = "O=CC(O)C(O)C(O)C(O)CO"
SEEDS = (GLUCOSE, GLUCOSE_OPEN)

# Human-set targets (policy/targets_and_budget.md). Kept in sync with
# scripts/graph/build_reaction_network.py::TARGETS.
TARGETS = {
    "HMF": "O=Cc1ccc(CO)o1",
    "HAA": "O=CCO",
    "FF": "O=Cc1ccco1",
}


def _load_net() -> dict:
    net_path = os.path.join(CP.GRAPH, "reaction_network.json")
    if not os.path.isfile(net_path):
        return {}
    try:
        return json.load(open(net_path))
    except json.JSONDecodeError:
        return {}


def _confirmed_frontier(net: dict) -> list[str]:
    """Species the expansion frontier admits: STRICT ∪ evidence_ok, plus the seeds."""
    sys.path.insert(0, os.path.join(PKG, "scripts", "reflect"))
    try:
        import graph_views as GV  # noqa: WPS433

        reached, _ = GV.confirmed_nodes(net, view="working", seeds=list(SEEDS))
        out = sorted(s for s in reached if s and "." not in s)
        if out:
            return out
    except Exception:
        pass
    return sorted(SEEDS)


def _stalled_species(net: dict, limit: int = 8) -> list[dict]:
    """Confirmed species with tried out-edges but nothing confirmed leaving them.

    These are where the deterministic enumerator has already spent its options, so they
    are the most useful place to ask for a mechanism it cannot express.
    """
    edges = list((net.get("edges") or {}).values())
    tried, confirmed = {}, {}
    for e in edges:
        r = e.get("reactant")
        if not r:
            continue
        tried[r] = tried.get(r, 0) + 1
        if e.get("status") in ("STRICT", "evidence_ok", "validated", "qm_real"):
            confirmed[r] = confirmed.get(r, 0) + 1
    rows = [
        {"smiles": s, "edges_tried": n, "edges_confirmed": confirmed.get(s, 0)}
        for s, n in tried.items()
        if n >= 2 and confirmed.get(s, 0) == 0
    ]
    rows.sort(key=lambda r: -r["edges_tried"])
    return rows[:limit]


def load_summary() -> dict:
    net = _load_net()
    edges = list(net.get("edges", {}).values())
    hyps = list(net.get("hypotheses", {}).values())
    strict = [e for e in edges if e.get("status") == "STRICT"]
    proposed = [e for e in edges if e.get("status") == "proposed"]
    meta = net.get("meta") or {}
    return {
        "n_nodes": len(net.get("nodes", {})),
        "n_edges": len(edges),
        "n_strict": len(strict),
        "n_proposed": len(proposed),
        "n_hypotheses": len(hyps),
        "strict_edges": [
            {"reactant": e.get("reactant"), "product": e.get("product"), "kind": e.get("kind")}
            for e in strict[:20]
        ],
        "frontier_smiles": _confirmed_frontier(net),
        "stalled_species": _stalled_species(net),
        "pending_hypotheses": [
            {
                "reactant": h.get("reactant"),
                "product": h.get("product"),
                "kind": h.get("kind"),
                "mechanism": h.get("mechanism"),
            }
            for h in hyps
            if h.get("status") == "pending"
        ][:20],
        "targets_reachable_strict": meta.get("targets_reachable_strict") or {},
    }


def _assistant_text_from_pi_jsonl(raw: str) -> str:
    """Collect assistant text from pi --mode json event stream or session JSONL."""
    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        # streaming deltas
        ev = o.get("assistantMessageEvent")
        if isinstance(ev, dict) and ev.get("type") == "text_delta":
            chunks.append(ev.get("delta") or "")
            continue
        # final message envelopes
        msg = o.get("message") if o.get("type") in {"message", "message_end", "turn_end"} else None
        if o.get("type") == "message" and o.get("role") == "assistant":
            msg = o
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            texts = []
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text") or "")
            if texts:
                chunks = texts  # prefer final full text over deltas
        if o.get("type") == "agent_end":
            for m in o.get("messages") or []:
                if m.get("role") == "assistant":
                    texts = [
                        c.get("text") or ""
                        for c in (m.get("content") or [])
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    if texts:
                        chunks = texts
    return "\n".join(chunks).strip()


def extract_json(text: str):
    text = (text or "").strip()
    if not text:
        return None
    # If this is a pi JSONL stream, unwrap assistant text first.
    if '"type":' in text[:200] or "\n{\"type\":" in text:
        unwrapped = _assistant_text_from_pi_jsonl(text)
        if unwrapped:
            text = unwrapped
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "content" in obj:
            return extract_json(
                obj["content"] if isinstance(obj["content"], str) else json.dumps(obj["content"])
            )
        return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    for opener, closer in (("[", "]"), ("{", "}")):
        i = text.find(opener)
        j = text.rfind(closer)
        if i >= 0 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    return None


def call_pi(prompt: str) -> str:
    env = os.environ.copy()
    cmd = [
        os.path.join(PKG, "loop", "pi_call.sh"),
    ]
    # TOOL_FLAGS already defaults to --no-tools in pi_call.sh
    env["TOOL_FLAGS"] = "--no-tools"
    env["SKILL_FLAGS"] = ""
    r = subprocess.run(
        cmd + [prompt],
        cwd=PKG,
        env=env,
        text=True,
        capture_output=True,
        timeout=600,
    )
    out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    if r.returncode != 0:
        raise RuntimeError(f"pi_call failed rc={r.returncode}: {out[-2000:]}")
    # Fallback: if stdout has no recoverable text, read newest session file
    if not _assistant_text_from_pi_jsonl(out):
        sess_dir = os.path.join(PKG, ".agentcfg", "sessions")
        if os.path.isdir(sess_dir):
            files = sorted(
                (
                    os.path.join(sess_dir, f)
                    for f in os.listdir(sess_dir)
                    if f.endswith(".jsonl")
                ),
                key=lambda p: os.path.getmtime(p),
            )
            if files:
                return open(files[-1]).read()
    return out


def _hyps_from_raw(raw: str) -> list:
    data = extract_json(raw)
    hyps = []
    if isinstance(data, list):
        hyps = data
    elif isinstance(data, dict):
        hyps = data.get("hypotheses") or data.get("candidates") or data.get("steps") or []
        if isinstance(hyps, dict):
            hyps = list(hyps.values())
    return [h for h in hyps if isinstance(h, dict)]


def _on_frontier(smiles: str, frontier: list) -> bool:
    return bool(smiles) and smiles in set(frontier)


def add_one(h: dict) -> dict:
    cmd = [
        CP.PYBIN,
        os.path.join(PKG, "scripts", "graph", "add_hypothesis.py"),
        "--reactant",
        h["reactant"],
        "--product",
        h["product"],
        "--kind",
        h.get("kind") or "unknown",
        "--mechanism",
        h.get("mechanism") or "",
        "--source",
        "explore_llm",
        "--priority",
        str(float(h.get("priority") or 0.5)),
    ]
    if h.get("coproduct"):
        cmd += ["--coproduct", h["coproduct"]]
    r = subprocess.run(cmd, cwd=PKG, text=True, capture_output=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stdout": r.stdout, "stderr": r.stderr, "rc": r.returncode}


def _local_balance(h: dict) -> dict:
    import mass_balance as MB  # noqa: WPS433

    return MB.check(h.get("reactant"), h.get("product"), h.get("coproduct"))


# What the template enumerator can express, stated so the model is asked for the
# complement rather than for duplicates. Mirrors tools/expand/templates_expand.py:
# four RDKit reaction SMARTS plus graph-based hemiketal ring close/open.
TEMPLATE_COVERAGE = [
    "beta-elimination dehydration (HO-C-C-H -> C=C + H2O)",
    "keto->enol and enol->keto 1,2-H shift",
    "retro-aldol C-C cleavage beta to a carbonyl",
    "hemiketal/hemiacetal ring close and ring open (5-/6-membered)",
]

TEMPLATE_BLIND_SPOTS = [
    "concerted aromatization forming a furan ring (several bonds at once)",
    "1,3-H shifts and hydride shifts, including aldose<->ketose via two migrating H",
    "steps whose reaction centre spans two fragments",
    "rearrangements that move a carbon skeleton rather than a hydrogen or an OH",
]


def _gap_state(net_summary: dict, template_report: dict | None = None) -> dict:
    """What the deterministic path did not reach, for the prompt and the record.

    Replaces the earlier single-target stoichiometric ladder. The ladder assumed a
    carbon-preserving dehydration sequence, which is meaningless once HAA (C2) and
    furfural (C5) are targets.
    """
    net = _load_net()
    meta = net.get("meta") or {}
    reach = meta.get("targets_reachable_strict") or {}
    dist = meta.get("strict_distance_to_targets") or {}
    tr = template_report or {}
    return {
        "targets": TARGETS,
        "targets_reachable_strict": reach,
        "targets_unreachable": sorted(k for k, v in reach.items() if not v) or sorted(TARGETS),
        "strict_hops_to_target": dist,
        "template_enumerated_this_round": tr.get("n_enumerated"),
        "template_kinds_this_round": tr.get("by_kind") or {},
        "template_can_express": TEMPLATE_COVERAGE,
        "template_cannot_express": TEMPLATE_BLIND_SPOTS,
        "stalled_species": (net_summary or {}).get("stalled_species") or [],
    }


def run(top: int = 4, dry_run: bool = False, template_report: dict | None = None) -> dict:
    # Refresh graph first. Must capture: this module's stdout is the machine-readable
    # result that run_loop parses, and an uncaptured child summary concatenates two JSON
    # documents and makes the whole stage look like it failed.
    subprocess.run(
        [CP.PYBIN, os.path.join(PKG, "scripts", "graph", "build_reaction_network.py")],
        cwd=PKG,
        check=False,
        capture_output=True,
        text=True,
    )
    summary = load_summary()
    gaps = _gap_state(summary, template_report)

    # Reactants must be species the graph has actually confirmed (or a seed), so a
    # proposal cannot start from a molecule no route reaches.
    allowed = summary.get("frontier_smiles") or sorted(SEEDS)
    known_pairs = [
        {"reactant": h.get("reactant"), "product": h.get("product"), "kind": h.get("kind")}
        for h in (summary.get("pending_hypotheses") or [])
        if _on_frontier(h.get("reactant"), allowed)
    ]
    # Compact blob: dumping every pending hypothesis previously burned the model's
    # output budget on SMILES archaeology and returned no JSON (n_proposed=0).
    prompt_graph = {
        "n_strict": summary.get("n_strict"),
        "strict_edges": summary.get("strict_edges"),
        "already_proposed_from_these_reactants": known_pairs,
    }
    import mass_balance as MB  # noqa: WPS433

    target_formulas = {name: MB.formula(smi) for name, smi in TARGETS.items()}
    prompt = f"""You are exploring a reaction network for the aqueous acid-catalysed
valorization of glucose. Targets: {json.dumps(TARGETS)} (formulas {json.dumps(target_formulas)}).
Return ONLY a JSON array. First character must be '['. No analysis, no prose.

Up to {top} elementary-step hypotheses. Each element:
{{
  "reactant": "<SMILES>",
  "product": "<SMILES>",
  "coproduct": "<SMILES or null>",
  "kind": "<ring_opening|dehydration|tautomerization|ring_closure|aromatization|retro_aldol|other>",
  "mechanism": "<one-sentence bond-change hypothesis>",
  "priority": 0.0-1.0
}}

Hard requirements — a step violating these is rejected before any calculation:
- Atoms must be conserved: reactant atoms == product atoms + coproduct atoms.
  State the coproduct explicitly. A dehydration MUST have "coproduct": "O".
- One elementary step loses at most one water. Never two.
- A C-C cleavage must state the second fragment as the coproduct.
- Every reactant MUST be copied verbatim from frontier_species below.
- Do not repeat a pair in already_proposed_from_these_reactants.
- Return at least 1 and at most {top} items.

A deterministic enumerator has already been run this round over the same frontier. It
covers exactly these transformations, so proposing them again is wasted:
{json.dumps(gaps['template_can_express'], indent=2)}
It CANNOT express the following, which is what you are being asked for:
{json.dumps(gaps['template_cannot_express'], indent=2)}

What it produced this round (reaction kind -> count):
{json.dumps(gaps.get('template_kinds_this_round') or {}, indent=2)}

Where the network is stuck:
- targets with no STRICT route yet: {json.dumps(gaps['targets_unreachable'])}
- shortest STRICT hop count to each target: {json.dumps(gaps['strict_hops_to_target'])}
- species with several tried edges and nothing confirmed leaving them:
{json.dumps(gaps.get('stalled_species') or [], indent=2)}

frontier_species (use these verbatim as reactants):
{json.dumps(allowed, indent=2)}

Graph:
{json.dumps(prompt_graph, indent=2)}
"""
    if dry_run:
        return {
            "status": "dry_run",
            "path": "llm",
            "summary": summary,
            "gaps": gaps,
            "allowed_reactants": allowed,
            "prompt_chars": len(prompt),
        }

    def _accept(raw: str) -> list:
        return [h for h in _hyps_from_raw(raw) if _on_frontier(h.get("reactant"), allowed)]

    raw = call_pi(prompt)
    hyps = _accept(raw)
    retries = 0
    if not hyps:
        retries = 1
        hyps = _accept(
            call_pi(
                f"Return ONLY a JSON array of {top} elementary steps. First char '['.\n"
                f"Each reactant MUST be copied from {json.dumps(allowed)}.\n"
                f"Atoms must balance; a dehydration needs \"coproduct\": \"O\".\n"
                f"Do not repeat: {json.dumps(known_pairs)}.\n"
                f"These targets have no STRICT route yet: "
                f"{json.dumps(gaps['targets_unreachable'])}. No empty array. No prose."
            )
        )

    # Deterministic repair: hand back the exact atom deficit and the formula the product
    # must have, rather than discarding the hypothesis. Free-form repair failed on every
    # item in round 1 — the model kept returning a product with one carbon too many — so
    # the arithmetic is spelled out and it gets two tries.
    import mass_balance as MB  # noqa: WPS433

    repaired = 0
    checked = []
    for h in hyps[:top]:
        if not h.get("reactant") or not h.get("product"):
            continue
        bal = _local_balance(h)
        for _ in range(2):
            if bal["ok"]:
                break
            waters = 1 if (h.get("kind") or "").lower() == "dehydration" else 0
            want = MB.required_product_formula(h["reactant"], waters)
            fix = _accept(
                call_pi(
                    "This step does not conserve atoms and was rejected.\n"
                    f"{json.dumps({k: h.get(k) for k in ('reactant', 'product', 'coproduct', 'kind')})}\n"
                    f"reactant minus (product + coproduct) = {json.dumps(bal['delta'])}\n"
                    f"reactant formula is {MB.formula(h['reactant'])}. "
                    f"Its product MUST have formula {want}"
                    + (' with "coproduct": "O".' if waters else " and no coproduct.")
                    + "\nCount the atoms in your product before answering. Keep the same "
                    "reactant and the same intended bond change.\n"
                    "Return ONLY a JSON array with one corrected step. First char '['."
                )
            )
            if not fix:
                break
            h = fix[0]
            bal = _local_balance(h)
            if bal["ok"]:
                repaired += 1
        if not bal["ok"]:
            continue
        checked.append(h)

    results = [add_one(h) for h in checked]

    out = {
        "status": "ok",
        "path": "llm",
        "n_proposed": sum(1 for r in results if r.get("ok")),
        "n_rejected_by_gate": sum(1 for r in results if not r.get("ok")),
        "results": results,
        "summary_before": summary,
        "gaps": gaps,
        "explore_retries": retries,
        "explore_repaired": repaired,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    state = os.path.join(PKG, "evidence", "state", "loop")
    os.makedirs(state, exist_ok=True)
    # Machine contract for run_loop: prefer this file over stdout parsing.
    # (pi / child tools have previously leaked JSON onto stdout and made the
    # stage look like it failed even when this payload was correct.)
    last_path = os.path.join(state, "explore_last.json")
    with open(last_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(state, "explore_llm.jsonl"), "a") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = run(top=a.top, dry_run=a.dry_run)
    # Also print for interactive use; run_loop primarily reads explore_last.json.
    print(json.dumps(out, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
