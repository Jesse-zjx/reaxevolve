#!/usr/bin/env python3
"""Resolve an asset set: where its skills and tools live, and which skill fills which role.

The loop must be able to run against either asset set, because that is what the fixed-asset
comparison compares and what the replay pins. The two sets do not share skill names — skills were
renamed, merged and split — so anything that calls a skill by name works for exactly one set.
`loop/skill_runner.py` named two initial-set skills and therefore could not run against the final
set at all, which is the live tree.

Roles are declared in `assets/roles.json` and checked against `evolution/ASSET_RENAMES.json` by
`scripts/qa/test_asset_roles.py`.

  python loop/asset_set.py                  # the set the live tree carries
  python loop/asset_set.py --set initial
"""
from __future__ import annotations

import argparse
import json
import os

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLES = os.path.join(PKG, "assets", "roles.json")


class AssetSetError(RuntimeError):
    pass


def live_set_name(root: str | None = None) -> str:
    """Which set the tree at `root` carries, from its own version file."""
    root = root or PKG
    vf = os.path.join(root, "tools", "VERSIONS.json")
    if not os.path.isfile(vf):
        raise AssetSetError(f"no tools/VERSIONS.json under {root}: cannot tell which set this is")
    name = json.load(open(vf)).get("asset_set")
    if not name:
        raise AssetSetError(f"{vf} does not declare asset_set")
    return name


def set_root(name: str, root: str | None = None) -> str:
    """Directory holding that set's assets.

    The live tree *is* one of the sets — whichever its VERSIONS.json declares — so for that one the
    root is the tree itself and not a copy under assets/. Reading the live set from assets/ instead
    would silently evaluate a snapshot of it rather than the thing that actually runs.
    """
    root = root or PKG
    if name == live_set_name(root):
        return root
    cand = os.path.join(root, "assets", name)
    if not os.path.isdir(cand):
        raise AssetSetError(f"unknown asset set {name!r}: no {cand}")
    return cand


def roles(name: str, root: str | None = None) -> dict[str, list[str]]:
    with open(ROLES) as fh:
        blob = json.load(fh)
    sets = blob.get("sets") or {}
    if name not in sets:
        raise AssetSetError(
            f"asset set {name!r} has no role declaration in assets/roles.json; "
            f"declared: {sorted(sets)}"
        )
    return dict(sets[name])


def skill_dirs(name: str, role: str, root: str | None = None) -> list[str]:
    """Absolute directories of the skills filling `role` in set `name`.

    Raises rather than returning an empty list: a role that resolves to nothing would make the
    caller run a prompt naming a skill that was never loaded, which is the failure this module
    exists to remove.
    """
    base = set_root(name, root)
    rel = roles(name, root).get(role)
    if not rel:
        raise AssetSetError(f"asset set {name!r} declares no skill for role {role!r}")
    out = []
    for r in rel:
        d = os.path.join(base, r)
        if not os.path.isdir(d):
            raise AssetSetError(f"role {role!r} in set {name!r} names {r}, missing under {base}")
        out.append(d)
    return out


def skill_flags(name: str, role: str, root: str | None = None) -> str:
    return " ".join(f"--skill {d}" for d in skill_dirs(name, role, root))


def version_vector(name: str, root: str | None = None) -> dict:
    vf = os.path.join(set_root(name, root), "tools", "VERSIONS.json")
    if not os.path.isfile(vf):
        raise AssetSetError(f"set {name!r} has no tools/VERSIONS.json")
    return json.load(open(vf))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", dest="name", default=None)
    ap.add_argument("--role", default=None)
    a = ap.parse_args()
    name = a.name or live_set_name()
    print(f"asset set: {name}")
    print(f"root:      {os.path.relpath(set_root(name), PKG) or '.'}")
    v = version_vector(name)
    print(f"skills:    {len(v.get('skills') or {})}   tools: {len(v.get('tools') or {})}")
    for role in ([a.role] if a.role else sorted(roles(name))):
        try:
            dirs = [os.path.relpath(d, set_root(name)) for d in skill_dirs(name, role)]
            print(f"  {role:<20} {', '.join(dirs)}")
        except AssetSetError as e:
            print(f"  {role:<20} UNRESOLVED: {e}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
