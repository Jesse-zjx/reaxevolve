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
import urllib.request



def _load_genesis_env():
    """Fall back to reaxevolve/.env for OpenAI-compatible fully_auto calls."""
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


def propose(bundle: dict, prompt_path: str | None = None) -> dict:
    _load_genesis_env()
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
    user = json.dumps(bundle)[:120000]
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
                    "Return a revise proposal now: pick one whitelist asset "
                    "(.skills/generate-ts-guesses or .skills/diagnose-ts-failures preferred) "
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
