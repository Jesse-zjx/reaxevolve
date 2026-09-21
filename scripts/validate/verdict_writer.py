#!/usr/bin/env python3
"""Unique write entry for evidence / endpoint / verdict fields.

INV-WRITE: only this module may assign status ∈ {STRICT, evidence_ok, rejected, unresolved}
on attempt records and append to graph/verdicts.jsonl. Drivers call here; LLMs never do.

STRICT is granted only when policy/acceptance/check_strict_bar.check_step(...).pass is True.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Any, Mapping, MutableMapping, Optional

_PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
if os.path.join(_PKG, "scripts", "lib") not in sys.path:
    sys.path.insert(0, os.path.join(_PKG, "scripts", "lib"))

ALLOWED = frozenset({"STRICT", "evidence_ok", "rejected", "unresolved"})
STRICT_VERSION_PATH = os.path.join(_PKG, "policy", "acceptance", "VERSION")
VERSIONS_PATH = os.path.join(_PKG, "tools", "VERSIONS.json")
VERDICTS_PATH = os.path.join(_PKG, "graph", "canonical", "verdicts.jsonl")
# Fallback during migration before graph/canonical exists as sole location
VERDICTS_FALLBACK = os.path.join(_PKG, "graph", "verdicts.jsonl")


def read_strict_version() -> str:
    try:
        return open(STRICT_VERSION_PATH).read().strip() or "v5"
    except OSError:
        return "v5"


def read_asset_versions() -> dict:
    """Full tools/VERSIONS.json vector — required on every attempt for §9.1 replay."""
    try:
        return json.load(open(VERSIONS_PATH))
    except (OSError, json.JSONDecodeError):
        return {"_missing": True}


def normalize_status(status: str, detail: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Map legacy status strings into the four-way vocabulary + detail."""
    if status in ALLOWED:
        return status, detail
    s = status or ""
    if s == "STRICT" or s.startswith("STRICT"):
        return "STRICT", detail or (s if s != "STRICT" else None)
    if s in ("MISMATCH", "PARTIAL_MATCH"):
        return "rejected", detail or s
    if s in ("validated", "qm_real"):
        return "evidence_ok", detail or s
    # Early-outs and failures: keep payload in detail, not in status.
    if s.startswith("NOT_CLEAN_TS") or s.startswith("TS_") or s.startswith("IRC_"):
        return "unresolved", detail or s
    if "imag modes=" in s or "GEOM_FUSED" in s:
        return "unresolved", detail or s
    return "unresolved", detail or s


def adjudicate_with_policy(
    ts_out: str,
    irc_f: Optional[str],
    irc_b: Optional[str],
    reactant: Optional[str] = None,
    product: Optional[str] = None,
    name: str = "step",
    coproduct: Optional[str] = None,
) -> dict:
    """Run STRICT(v5) checker; return check_step result + mapped status.

    `coproduct` is required for clause 3 on a real dehydration: the product-side IRC
    endpoint carries two fragments (product + H2O), and without the expected coproduct
    the checker compares them against the organic product alone and always fails. That
    omission rejected every dehydration in the campaign — including steps whose own
    recorded endpoint_match was double-ended with a single imaginary mode — which is why
    all four STRICT edges so far are formula-preserving. STRICT.md clause 4 explicitly
    admits "a real dehydration (-3 atoms with water as a genuine product)", so this
    restores the written bar rather than relaxing it.
    """
    pol = os.path.join(_PKG, "policy", "acceptance")
    if pol not in sys.path:
        sys.path.insert(0, pol)
    import check_strict_bar as bar  # noqa: E402

    r = bar.check_step(name, ts_out, irc_f, irc_b, reactant, product, coproduct=coproduct)
    if r.get("pass"):
        status, detail = "STRICT", None
    else:
        # QM ran and produced endpoints but failed a hard clause → rejected;
        # missing IRC / unparsed → unresolved.
        if r.get("endpoints_ok") is False or r.get("water_ok") is False:
            status, detail = "rejected", "; ".join(r.get("notes") or []) or "clause fail"
        elif r.get("single_imag") is False:
            status, detail = "rejected", f"imag={r.get('imag')}"
        else:
            status, detail = "unresolved", "; ".join(r.get("notes") or []) or "incomplete"
    r["status"] = status
    r["detail"] = detail
    r["strict_version"] = read_strict_version()
    return r


def hypothesis_id(reactant: str, product: str) -> str:
    """Stable hypothesis key, matching scripts/graph/add_hypothesis.py."""
    return "H_" + hashlib.sha1(f"{reactant}>>{product}".encode()).hexdigest()[:12]


def input_fingerprint(paths) -> Optional[dict]:
    """Content hashes of the files this attempt was computed from.

    An attempt is identified by hypothesis, guess method, asset versions, QM protocol and the
    job itself. Without a hash of the inputs the last part is missing, so two attempts that
    differ only in their starting geometry are indistinguishable in the record — and a replay
    cannot prove it re-ran the same job.
    """
    out = {}
    for p in paths or []:
        try:
            with open(p, "rb") as fh:
                out[os.path.basename(p)] = hashlib.sha256(fh.read()).hexdigest()[:16]
        except OSError:
            continue
    return out or None


def stamp(
    record: MutableMapping[str, Any],
    status: str,
    detail: Optional[str] = None,
    input_paths=None,
) -> dict:
    """Mutate and return record with status/detail/strict_version/asset_versions/identity."""
    st, det = normalize_status(status, detail)
    if st not in ALLOWED:
        raise ValueError(f"illegal status {st!r}")
    record["status"] = st
    if det:
        record["detail"] = det
    elif "detail" in record and st == "STRICT":
        record.pop("detail", None)
    record["strict_version"] = read_strict_version()
    record["asset_versions"] = read_asset_versions()
    r, p = record.get("reactant"), record.get("product")
    if r and p and "hypothesis_id" not in record:
        record["hypothesis_id"] = hypothesis_id(r, p)
    fp = input_fingerprint(input_paths)
    if fp:
        record.setdefault("input_fingerprint", fp)
    if "time" not in record:
        record["time"] = time.strftime("%Y-%m-%d %H:%M")
    return dict(record)


def write_strict_cache(
    cache_path: str,
    edge_key: str,
    record: Mapping[str, Any],
    status: str,
    detail: Optional[str] = None,
    input_paths=None,
) -> dict:
    """Write one attempt into a run-local strict_cache.json via the unique entry point."""
    data: dict = {}
    if os.path.exists(cache_path):
        try:
            data = json.load(open(cache_path))
        except json.JSONDecodeError:
            data = {}
    rec = stamp(dict(record), status, detail, input_paths=input_paths)
    data[edge_key] = rec
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)) or ".", exist_ok=True)
    json.dump(data, open(cache_path, "w"), indent=2)
    return rec


def append_verdict(record: Mapping[str, Any], source: Optional[str] = None) -> None:
    """Append one frozen judgement line (idempotent enough for consolidate; caller dedups)."""
    path = VERDICTS_PATH if os.path.isdir(os.path.dirname(VERDICTS_PATH)) else VERDICTS_FALLBACK
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = dict(record)
    if source:
        row["source"] = source
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
