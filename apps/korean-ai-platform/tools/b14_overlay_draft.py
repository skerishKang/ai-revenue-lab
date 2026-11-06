"""Draft a B14 Owner overlay from a base registry plus reasoning blocks.

An overlay model row replaces the base row whole, so a partial row aborts the
next boot. This tool copies each selected base row verbatim, attaches only the
requested reasoning block, and runs the same merge + validation the application
runs at boot before anything is printed or written.

Draft input (one JSON file)::

    {"models": {"<model id>": {"supported": true, "values": ["low", "high"]}}}

Usage::

    python tools/b14_overlay_draft.py --base app/pilot/b14_models.json \
        --draft draft.json --out b14_models.overrides.json
    python tools/b14_overlay_draft.py --base app/pilot/b14_models.json \
        --check b14_models.overrides.json

Exit status is 0 only when the effective registry validates. Failures name the
model and the key at fault wherever the fault belongs to a chosen row.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))
_CORE_SOURCE = _APP_ROOT.parents[1] / "packages" / "padiem-ai-core"
if (_CORE_SOURCE / "padiem_ai_core").is_dir() and str(_CORE_SOURCE) not in sys.path:
    sys.path.insert(0, str(_CORE_SOURCE))

from app.pilot.model_registry_file import (  # noqa: E402
    ModelRegistryError,
    merge_overlay,
    validate_registry,
)
from app.pilot.reasoning_policy import normalize_policy  # noqa: E402

_MODEL_KEYS = frozenset({
    "id", "provider_id", "upstream_model", "display_name", "provider_name",
    "capabilities", "context_window", "input_price_usd_per_1m",
    "output_price_usd_per_1m", "source", "source_checked_at", "enabled",
})
_OPTIONAL_MODEL_KEYS = frozenset({"reasoning"})


class DraftError(ValueError):
    """A draft that cannot become a validated overlay."""


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DraftError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise DraftError(f"invalid JSON in {path}: {exc}") from exc


def _diagnose_row(row: object, fallback: str) -> str:
    if not isinstance(row, dict):
        return f"{fallback}: model row must be an object"
    model_id = row.get("id")
    label = model_id if isinstance(model_id, str) and model_id else fallback
    missing = sorted(_MODEL_KEYS - set(row))
    if missing:
        return f"{label}: missing keys: {', '.join(missing)}"
    unexpected = sorted(set(row) - _MODEL_KEYS - _OPTIONAL_MODEL_KEYS)
    if unexpected:
        return f"{label}: unexpected keys: {', '.join(unexpected)}"
    if "reasoning" in row:
        try:
            normalize_policy(row["reasoning"])
        except ValueError as exc:
            return f"{label}: reasoning: {exc}"
    return ""


def _base_rows(base: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for index, row in enumerate(base.get("models") or []):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise DraftError(f"base registry: models[{index}] has no string id")
        rows[row["id"]] = row
    return rows


def _build_overlay(base: dict, draft: object) -> dict:
    if not isinstance(draft, dict) or set(draft) != {"models"}:
        raise DraftError('draft: expected exactly {"models": {<model id>: <reasoning block>}}')
    wanted = draft["models"]
    if not isinstance(wanted, dict) or not wanted:
        raise DraftError("draft.models must be a non-empty mapping of model id to reasoning block")
    base_rows = _base_rows(base)
    if not base_rows:
        raise DraftError("base registry has no model rows")
    rows = []
    for model_id, block in wanted.items():
        if not isinstance(model_id, str) or not model_id:
            raise DraftError("draft.models keys must be model ids")
        source = base_rows.get(model_id)
        if source is None:
            raise DraftError(f"{model_id}: not present in the base registry")
        try:
            normalize_policy(block)
        except ValueError as exc:
            raise DraftError(f"{model_id}: reasoning: {exc}") from exc
        row = json.loads(json.dumps(source))
        row["reasoning"] = json.loads(json.dumps(block))
        rows.append(row)
    return {"schema_version": 1, "models": rows}


def _validated_effective(base: dict, overlay: dict) -> dict:
    try:
        effective = merge_overlay(base, overlay)
        validate_registry(effective)
    except ModelRegistryError as exc:
        raise DraftError(f"overlay validation failed: {exc}") from exc
    return effective


def _check(base: dict, overlay_path: Path) -> tuple[dict, dict]:
    overlay = _load_json(overlay_path)
    if not isinstance(overlay, dict):
        raise DraftError(f"{overlay_path}: overlay root must be an object")
    rows = overlay.get("models") or []
    if not isinstance(rows, list):
        raise DraftError(f"{overlay_path}: overlay models must be a list")
    for index, row in enumerate(rows):
        diagnosis = _diagnose_row(row, f"models[{index}]")
        if diagnosis:
            raise DraftError(f"{overlay_path}: {diagnosis}")
    effective = _validated_effective(base, overlay)
    return overlay, effective


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, type=Path,
                        help="base b14_models.json the overlay is applied on top of")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--draft", type=Path,
                      help="JSON file mapping model id to its reasoning block")
    mode.add_argument("--check", type=Path,
                      help="existing overlay file to validate without writing")
    parser.add_argument("--out", type=Path,
                        help="write the validated overlay here instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        base = _load_json(args.base)
        if not isinstance(base, dict):
            raise DraftError(f"{args.base}: registry root must be an object")
        if args.check is not None:
            if args.out is not None:
                raise DraftError("--out cannot be used with --check")
            overlay, effective = _check(base, args.check)
            print(
                f"OK: {args.check} providers={len(overlay.get('providers') or {})} "
                f"models={len(overlay.get('models') or [])} "
                f"retired={len(overlay.get('retired_models') or [])} "
                f"effective_models={len(effective['models'])}"
            )
            return 0

        overlay = _build_overlay(base, _load_json(args.draft))
        effective = _validated_effective(base, overlay)
        text = json.dumps(overlay, ensure_ascii=False, indent=2) + "\n"
        if args.out is not None:
            try:
                args.out.write_text(text, encoding="utf-8")
            except OSError as exc:
                raise DraftError(f"cannot write {args.out}: {exc}") from exc
            print(f"wrote {args.out} models={len(overlay['models'])} "
                  f"effective_models={len(effective['models'])}")
        else:
            sys.stdout.write(text)
        return 0
    except DraftError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
