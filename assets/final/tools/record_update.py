#!/usr/bin/env python3
"""Safely update the current round block in a ReactionAgent record.json file."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROUND_KEYS = {"generation_policy", "guesses", "diagnosis_feedback"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate record.json shape.")
    validate_parser.add_argument("--record", required=True, help="Path to record.json.")

    guesses_parser = subparsers.add_parser("set-guesses", help="Set record[-1].guesses.")
    guesses_parser.add_argument("--record", required=True, help="Path to record.json.")
    guesses_parser.add_argument("--json-file", required=True, help="Path to a JSON list of guesses.")
    guesses_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an already non-empty record[-1].guesses list.",
    )

    feedback_parser = subparsers.add_parser(
        "set-diagnosis-feedback",
        help="Set record[-1].diagnosis_feedback.",
    )
    feedback_parser.add_argument("--record", required=True, help="Path to record.json.")
    feedback_parser.add_argument("--json-file", required=True, help="Path to a JSON list of feedback entries.")
    feedback_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an already non-empty record[-1].diagnosis_feedback list.",
    )

    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def validate_record(record: Any) -> list[dict[str, Any]]:
    if not isinstance(record, list) or not record:
        raise ValueError("record.json must be a non-empty JSON list.")

    for index, block in enumerate(record):
        if not isinstance(block, dict):
            raise ValueError(f"record[{index}] must be an object.")
        keys = set(block)
        if not ROUND_KEYS.issubset(keys):
            raise ValueError(f"record[{index}] must contain at least {sorted(ROUND_KEYS)}, got {sorted(keys)}.")
        if not isinstance(block["generation_policy"], dict):
            raise ValueError(f"record[{index}].generation_policy must be an object.")
        if not isinstance(block["guesses"], list):
            raise ValueError(f"record[{index}].guesses must be a list.")
        if not isinstance(block["diagnosis_feedback"], list):
            raise ValueError(f"record[{index}].diagnosis_feedback must be a list.")

    return record


def load_record(path: Path) -> list[dict[str, Any]]:
    return validate_record(load_json(path))


def validate_payload_list(payload: Any, *, name: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError(f"{name} payload must be a JSON list.")
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"{name}[{index}] must be an object.")
    return payload


def require_field(item: dict[str, Any], field: str, *, path: str) -> None:
    value = item.get(field)
    if value is None or value == "":
        raise ValueError(f"{path}.{field} is required.")


def validate_guesses(payload: Any) -> list[dict[str, Any]]:
    guesses = validate_payload_list(payload, name="guesses")
    for index, guess in enumerate(guesses):
        require_field(guess, "guess_id", path=f"guesses[{index}]")
        require_field(guess, "xyz_path", path=f"guesses[{index}]")
    return guesses


def validate_feedback(payload: Any) -> list[dict[str, Any]]:
    feedback = validate_payload_list(payload, name="diagnosis_feedback")
    for index, entry in enumerate(feedback):
        require_field(entry, "guess_id", path=f"diagnosis_feedback[{index}]")
        require_field(entry, "branch_decision", path=f"diagnosis_feedback[{index}]")
        require_field(entry, "diagnosis", path=f"diagnosis_feedback[{index}]")
    return feedback


def set_current_round_field(
    *,
    record_path: Path,
    field: str,
    payload: list[dict[str, Any]],
    overwrite: bool,
) -> None:
    record = load_record(record_path)
    current_block = record[-1]
    if current_block[field] and not overwrite:
        raise ValueError(f"record[-1].{field} is already non-empty. Use --overwrite to replace it.")

    current_block[field] = payload
    validate_record(record)
    dump_json_atomic(record_path, record)


def main() -> int:
    args = parse_args()
    record_path = Path(args.record).resolve()

    if args.command == "validate":
        load_record(record_path)
        print(record_path)
        return 0

    payload_path = Path(args.json_file).resolve()
    payload = load_json(payload_path)
    if args.command == "set-guesses":
        guesses = validate_guesses(payload)
        set_current_round_field(
            record_path=record_path,
            field="guesses",
            payload=guesses,
            overwrite=args.overwrite,
        )
    elif args.command == "set-diagnosis-feedback":
        feedback = validate_feedback(payload)
        set_current_round_field(
            record_path=record_path,
            field="diagnosis_feedback",
            payload=feedback,
            overwrite=args.overwrite,
        )
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(record_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
