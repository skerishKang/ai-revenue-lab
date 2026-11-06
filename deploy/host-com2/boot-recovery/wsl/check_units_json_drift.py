#!/usr/bin/env python3
"""Report unit-list or required-flag drift without modifying either file."""

import json
import sys
from pathlib import Path
from typing import Any


MISSING = object()


def load_required_by_unit(path: Path) -> dict[str, bool]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("units") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("units must be a list")

    required_by_unit: dict[str, bool] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("unit"), str):
            raise ValueError("each unit entry must have a string unit name")
        unit = entry["unit"]
        if unit in required_by_unit:
            raise ValueError(f"duplicate unit: {unit}")
        # Match boot_recovery.py, which treats an omitted required flag as true.
        required_by_unit[unit] = bool(entry.get("required", True))
    return required_by_unit


def display_required(value: object) -> str:
    if value is MISSING:
        return "MISSING"
    return "true" if value else "false"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print("UNITS_JSON_DRIFT=YES")
        print("UNITS_JSON_DRIFT_DETAIL=INVALID_ARGUMENTS")
        return 0

    server_path, example_path = map(Path, arguments)
    try:
        example = load_required_by_unit(example_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        print("UNITS_JSON_DRIFT=YES")
        print("UNITS_JSON_DRIFT_DETAIL=EXAMPLE_JSON_INVALID")
        return 0

    try:
        server = load_required_by_unit(server_path)
        server_missing = False
    except FileNotFoundError:
        server = {}
        server_missing = True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        print("UNITS_JSON_DRIFT=YES")
        print("UNITS_JSON_DRIFT_DETAIL=SERVER_JSON_INVALID")
        return 0

    unit_names = sorted(set(server) | set(example))
    differences = [
        unit for unit in unit_names
        if server_missing
        or server.get(unit, MISSING) != example.get(unit, MISSING)
    ]
    if not differences:
        print("UNITS_JSON_DRIFT=NO")
        return 0

    print("UNITS_JSON_DRIFT=YES")
    for unit in differences:
        server_required = MISSING if server_missing else server.get(unit, MISSING)
        example_required = example.get(unit, MISSING)
        print(
            "UNITS_JSON_DRIFT_ENTRY "
            f"unit={json.dumps(unit, ensure_ascii=False)} "
            f"SERVER_REQUIRED={display_required(server_required)} "
            f"EXAMPLE_REQUIRED={display_required(example_required)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
