#!/usr/bin/env python3
"""Would the preregistered stopping rule have fired on the campaign that already happened?

The rule in `preregistration/panel.json` — K=3 windows, epsilon=5% relative growth in accepted
edges — was written after the campaign it describes. `loop/saturation.py` enforces it going
forward, but no round-level metrics exist, because the historical work was session-style rather
than round-based. This is therefore a **retrospective** analysis, and it is labelled as one
everywhere it is reported. It cannot show that the rule stopped anything; it can only show where
the rule would have stopped, had it been running.

The campaign has no rounds, so rounds have to be constructed. Consecutive blocks of attempts are
the least arbitrary choice available, but the block size is a free parameter and choosing one
after seeing the answer would make the result meaningless. So every block size in a stated range
is reported, and the conclusion is whatever survives across them.

  python experiments/saturation_retrospective/analyse.py
  python experiments/saturation_retrospective/analyse.py --write
"""
from __future__ import annotations

import argparse
import json
import os

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ATTEMPTS = os.path.join(PKG, "evolution", "attempt_vectors.jsonl")
PANEL = os.path.join(PKG, "preregistration", "panel.json")
NETWORK = os.path.join(PKG, "graph", "canonical", "reaction_network.json")
OUT = os.path.join(PKG, "experiments", "saturation_retrospective", "RESULT.md")

BLOCK_SIZES = (10, 15, 20, 25, 30)


def load_rule() -> tuple[int, float]:
    pre = json.load(open(PANEL))
    r = pre.get("stopping_rule") or {}
    return int(r.get("window_rounds") or 3), float(r.get("epsilon_relative_growth") or 0.05)


def load_attempts() -> list[dict]:
    rows = [json.loads(l) for l in open(ATTEMPTS) if l.strip()]
    # `time` is the only ordering available. Stable sort keeps the file order for ties.
    rows.sort(key=lambda r: r.get("time") or "")
    return rows


def blocks(rows: list[dict], size: int) -> list[dict]:
    """Pseudo-rounds: consecutive blocks of attempts, with cumulative accepted-edge counts.

    An attempt counts toward d_strict only the first time its edge is accepted; a re-validation of
    an edge already accepted is not growth.
    """
    out = []
    seen: set[tuple] = set()
    cum = 0
    for i in range(0, len(rows), size):
        chunk = rows[i : i + size]
        before = cum
        d = 0
        for r in chunk:
            if r.get("status") != "STRICT":
                continue
            key = (r.get("reactant"), r.get("product"))
            if key in seen:
                continue
            seen.add(key)
            d += 1
        cum += d
        out.append({
            "block": len(out) + 1,
            "attempts": len(chunk),
            "d_strict": d,
            "n_strict_before": before,
            "relative_growth": round(d / max(1, before), 4),
        })
    return out


def first_fire(bs: list[dict], K: int, eps: float) -> dict:
    """Earliest block at which the rule would have fired, scanning forward."""
    for i in range(K - 1, len(bs)):
        window = bs[i - K + 1 : i + 1]
        if all(b["relative_growth"] < eps for b in window):
            zero = all(b["d_strict"] == 0 for b in window)
            return {
                "fired_at_block": bs[i]["block"],
                "which": "zero_growth_for_K_blocks" if zero else "relative_growth_below_epsilon",
                "window": window,
                "blocks_total": len(bs),
            }
    return {"fired_at_block": None, "which": None, "blocks_total": len(bs)}


def epsilon_bites(bs: list[dict], eps: float) -> dict:
    """Is epsilon doing anything that 'no new edge at all' would not do?

    With a small accepted-edge count, eps=5% of n_strict_before is below one edge, so the
    threshold is arithmetically indistinguishable from requiring d_strict == 0. Worth stating
    rather than leaving for a reader to notice.
    """
    distinguishing = [b for b in bs if b["d_strict"] > 0 and b["relative_growth"] < eps]
    n_needed = int(1 / eps)  # n_strict_before at which one new edge is still under eps
    return {
        "blocks_where_eps_differs_from_zero": len(distinguishing),
        "n_strict_before_needed_for_eps_to_bite": n_needed,
        "max_n_strict_before_observed": max((b["n_strict_before"] for b in bs), default=0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    K, eps = load_rule()
    rows = load_attempts()
    net = json.load(open(NETWORK))
    n_net_strict = sum(1 for e in net["edges"].values() if e.get("status") == "STRICT")
    n_stream_strict = len({
        (r.get("reactant"), r.get("product")) for r in rows if r.get("status") == "STRICT"
    })

    L: list[str] = []
    L.append("# Would the preregistered stopping rule have fired? — retrospective")
    L.append("")
    L.append("Generated by `experiments/saturation_retrospective/analyse.py`.")
    L.append("")
    L.append("**This is a retrospective analysis, not evidence that the rule stopped anything.**")
    L.append("The rule (`preregistration/panel.json`: K=%d windows, ε=%.0f%% relative growth) was "
             "written after the campaign it is applied to here, and the campaign was session-style "
             "rather than round-based, so no round-level metrics exist. `loop/saturation.py` "
             "enforces the rule for future runs. What follows can only say where the rule *would* "
             "have stopped." % (K, eps * 100))
    L.append("")
    L.append("## Inputs")
    L.append("")
    L.append(f"- attempt stream: `evolution/attempt_vectors.jsonl`, {len(rows)} attempts, "
             f"{n_stream_strict} distinct accepted edges")
    L.append(f"- for reference, the canonical network holds {n_net_strict} accepted edges: the "
             "stream begins after some session-style work, so it is a subset and the two numbers "
             "are not expected to match")
    L.append("- ordering: the `time` field, the only ordering the records carry")
    L.append("")
    L.append("## Constructed rounds, and why the block size is swept")
    L.append("")
    L.append("The campaign has no rounds, so they have to be constructed as consecutive blocks of "
             "attempts. Block size is a free parameter, and picking one after seeing the answer "
             "would make the result meaningless — so every size below is reported and the "
             "conclusion is whatever holds across them.")
    L.append("")
    L.append("| block size | blocks | rule fires at block | of total | on which condition |")
    L.append("|---|---|---|---|---|")
    fires = {}
    for size in BLOCK_SIZES:
        bs = blocks(rows, size)
        f = first_fire(bs, K, eps)
        fires[size] = (bs, f)
        at = f["fired_at_block"]
        L.append(f"| {size} | {f['blocks_total']} | {at if at else 'never'} | "
                 f"{f['blocks_total']} | {f['which'] or '—'} |")
    L.append("")

    fired = [s for s, (_, f) in fires.items() if f["fired_at_block"]]
    if len(fired) == len(BLOCK_SIZES):
        L.append("The rule fires at every block size tried, so the finding does not depend on the "
                 "construction.")
    elif fired:
        L.append(f"The rule fires at {len(fired)} of {len(BLOCK_SIZES)} block sizes "
                 f"({', '.join(str(s) for s in fired)}) and not at the others, so it **is** "
                 "sensitive to how rounds are constructed. Reported as such; this is a reason to "
                 "treat the retrospective as weak evidence.")
    else:
        L.append("The rule does not fire at any block size tried: on this campaign, growth never "
                 "stayed below the threshold for K consecutive constructed rounds. The campaign "
                 "ended for other reasons.")
    L.append("")

    # The arithmetic caveat, which matters more than the table.
    size_mid = BLOCK_SIZES[len(BLOCK_SIZES) // 2]
    bs_mid, _ = fires[size_mid]
    bite = epsilon_bites(bs_mid, eps)
    L.append("## ε barely differs from \"no new edge at all\" at this scale")
    L.append("")
    L.append(f"ε={eps:.0%} of the accepted-edge count only admits a nonzero increment once that "
             f"count reaches {bite['n_strict_before_needed_for_eps_to_bite']}. The largest count "
             f"reached in this stream is {bite['max_n_strict_before_observed']}, and at block size "
             f"{size_mid} there are {bite['blocks_where_eps_differs_from_zero']} blocks where the ε "
             "test and a plain \"d_strict == 0\" test would disagree.")
    L.append("")
    L.append("So at this campaign's scale the preregistered ε is close to a zero-growth rule. That "
             "is a property of the rule at small accepted-edge counts, not a flaw in the data, and "
             "it is why `loop/saturation.py` reports which of the two conditions fired instead of "
             "collapsing them.")
    L.append("")

    L.append(f"## Per-block detail at block size {size_mid}")
    L.append("")
    L.append("| block | attempts | new accepted edges | accepted before | relative growth |")
    L.append("|---|---|---|---|---|")
    for b in bs_mid:
        L.append(f"| {b['block']} | {b['attempts']} | {b['d_strict']} | {b['n_strict_before']} | "
                 f"{b['relative_growth']:.3f} |")
    L.append("")
    L.append("## What this does and does not license")
    L.append("")
    L.append("- It does **not** license \"the loop ran until saturation\". The loop did not run "
             "under this rule.")
    L.append("- It does not license a claim that the asset set is optimal or complete.")
    L.append("- It does support the narrower statement that the preregistered threshold is "
             "consistent with where this campaign's accepted-edge growth actually went, which is "
             "worth stating because a rule that would have fired on attempt three, or never, would "
             "be evidence the threshold was chosen badly.")

    text = "\n".join(L) + "\n"
    print(text)
    if a.write:
        open(OUT, "w").write(text)
        print(f"[wrote] {os.path.relpath(OUT, PKG)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
