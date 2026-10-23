#!/usr/bin/env python3
"""LLM client for fully_auto Reflect.

Configure via env:
  CHEM_FULLY_AUTO_BASE_URL  OpenAI-compatible base URL
  CHEM_FULLY_AUTO_API_KEY   API key
  CHEM_FULLY_AUTO_MODEL     model id

If unset, `propose()` returns action=noop (safe default).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from apply_revision import PROTECTED  # noqa: E402



def _load_repo_env():
    """Fall back to the repository .env for OpenAI-compatible Reflect calls."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    if not os.path.isfile(env_path):
        return
    for line in open(env_path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
    if not os.environ.get("CHEM_FULLY_AUTO_BASE_URL") and os.environ.get("BASE_URL"):
        os.environ["CHEM_FULLY_AUTO_BASE_URL"] = os.environ["BASE_URL"]
    if not os.environ.get("CHEM_FULLY_AUTO_API_KEY") and os.environ.get("API_KEY"):
        os.environ["CHEM_FULLY_AUTO_API_KEY"] = os.environ["API_KEY"]
    if not os.environ.get("CHEM_FULLY_AUTO_MODEL") and os.environ.get("MODEL_NAME"):
        os.environ["CHEM_FULLY_AUTO_MODEL"] = os.environ["MODEL_NAME"]


def _chat(base: str, key: str, model: str, messages: list, temperature: float = 0.2) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def _parse_proposal(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {"action": "noop", "reason": "unparseable model output", "raw": text[:2000]}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"action": "noop", "reason": "json decode failed", "raw": text[:2000]}


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _live_inventory(pkg: str | None = None) -> dict:
    """Evolvable paths, excluding evidence parsers. File bodies are filled by _user_message."""
    pkg = pkg or _repo_root()
    protected = set(PROTECTED)
    skills_root = os.path.join(pkg, ".skills")
    skills = []
    if os.path.isdir(skills_root):
        for name in sorted(os.listdir(skills_root)):
            rel = ".skills/" + name + "/SKILL.md"
            if os.path.isfile(os.path.join(pkg, rel)):
                skills.append(rel)
    tools = []
    vers_path = os.path.join(pkg, "tools", "VERSIONS.json")
    try:
        vers = json.load(open(vers_path))
        for k in vers.get("tools") or {}:
            if k == "guess":
                continue
            rel = "tools/" + k
            if rel in protected or k in {
                "geometry/parse_orca_output.py",
                "geometry/xyz_to_smiles.py",
            }:
                continue
            if os.path.isfile(os.path.join(pkg, rel)):
                tools.append(rel)
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "skills": skills,
        "tools": tools,
        "protected": sorted(protected),
        "files": {},
        "omitted_files": [],
        "note": (
            "Patch against files[path] only. Do not propose a path in protected "
            "or omitted_files. Omitted files are absent because they did not fit "
            "with a complete bundle; this call cannot read the disk."
        ),
    }


USER_CHAR_BUDGET = 120000


def _user_message(bundle: dict, pkg: str | None = None, budget: int = USER_CHAR_BUDGET) -> str:
    """Keep the reflect bundle intact; add only complete source files that fit.

    The HTTP call cannot read the repository. Truncating the final JSON used to
    drop the bundle (failure evidence and must_revise). Truncating a file and
    saying 'read the rest on disk' is equally useless.
    """
    pkg = pkg or _repo_root()
    inv = _live_inventory(pkg)
    texts: list[tuple[str, str]] = []
    for rel in list(inv.get("skills") or []) + list(inv.get("tools") or []):
        path = os.path.join(pkg, rel)
        if os.path.isfile(path):
            texts.append((rel, open(path, errors="replace").read()))
    texts.sort(key=lambda kv: (0 if kv[0].startswith(".skills/") else 1, len(kv[1]), kv[0]))

    files: dict[str, str] = {}
    omitted: list[str] = []

    def dump() -> str:
        payload = {
            "live_assets": {
                **inv,
                "files": files,
                "omitted_files": omitted,
            },
            "bundle": bundle,
        }
        return json.dumps(payload, indent=2)

    # Never slice dump(). If the bundle alone exceeds the budget, keep it whole.
    for rel, text in texts:
        files[rel] = text
        if len(dump()) > budget:
            del files[rel]
            omitted.append(rel)
    return dump()


def propose(bundle: dict, prompt_path: str | None = None) -> dict:
    _load_repo_env()
    base = os.environ.get("CHEM_FULLY_AUTO_BASE_URL", "").strip()
    key = os.environ.get("CHEM_FULLY_AUTO_API_KEY", "").strip()
    model = os.environ.get("CHEM_FULLY_AUTO_MODEL", "").strip()
    if not (base and key and model):
        return {
            "action": "noop",
            "reason": "CHEM_FULLY_AUTO_* env not configured",
            "bundle_time": bundle.get("time"),
        }
    prompt = open(prompt_path or os.path.join(os.path.dirname(__file__), "prompt.md")).read()
    user = _user_message(bundle)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user},
    ]
    prop = _parse_proposal(_chat(base, key, model, messages))
    must = bool((bundle.get("reflect_pressure") or {}).get("must_revise"))
    # One forced retry: first campaign died on repeated empty noops under must_revise.
    if must and prop.get("action") != "revise":
        retry_msgs = messages + [
            {"role": "assistant", "content": json.dumps(prop)[:4000]},
            {
                "role": "user",
                "content": (
                    "REJECTED: reflect_pressure.must_revise is true, so action=noop is forbidden. "
                    "Return a revise proposal now: pick one path that is actually present "
                    "in live_assets.files (not omitted_files or protected) "
                    "and supply a minimal concrete diff_unified addressing a dominant "
                    "failure_digest mode. JSON only."
                ),
            },
        ]
        prop2 = _parse_proposal(_chat(base, key, model, retry_msgs, temperature=0.3))
        prop2["retried_after_noop"] = True
        prop2["prior_action"] = prop.get("action")
        return prop2
    return prop


if __name__ == "__main__":
    print(json.dumps(propose({"time": "cli", "stage": "reflect"}), indent=2))
