"""Synthetic, repository-safe fixture loading for the generation pipeline.

Contract (PERSONAL_EDITION_MVP_CONTRACT.md section 12): development fixtures
must be synthetic or explicitly approved and redacted. No fixture may contain
real participant material, credentials, private endpoints, or live tokens.

This module loads JSON fixture bundles from a configurable directory. A bundle
groups everything the pipeline needs to run a single end-to-end scenario:
input text, language, prohibited inventions, allowed facts, and one or more
scripted provider responses (plan + draft) for the MockProvider.

Fixtures are plain data; they never touch a database or a network. They are
loaded lazily and cached, so repeated runs in a single process are cheap and
deterministic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.pipeline.errors import PipelineError

# Default fixture directory relative to the personal-edition package root.
DEFAULT_FIXTURES_DIR = "tests/fixtures"


class FixtureError(PipelineError):
    """Raised when a fixture bundle is missing, malformed, or unsafe."""


@dataclass(frozen=True)
class FixtureBundle:
    """A loaded fixture bundle for one end-to-end scenario."""

    name: str
    language: str
    input_text: str
    prohibited_inventions: tuple[str, ...]
    allowed_facts: tuple[str, ...]
    # Scripted provider responses keyed by task name. Each value is the raw
    # fixture dict the MockProvider returns for that task.
    plan_payload: dict[str, Any] | None
    draft_payload: dict[str, Any] | None
    # Optional second-edition plan/draft payloads for the feedback loop.
    follow_up_plan_payload: dict[str, Any] | None
    follow_up_draft_payload: dict[str, Any] | None
    # Optional feedback directions and free text that drive the second edition.
    feedback_directions: tuple[str, ...]
    feedback_free_text: str | None
    # Optional flag indicating the plan payload is intentionally invalid for
    # adversarial tests (the MockProvider still returns it verbatim).
    notes: dict[str, Any]


_CACHE: dict[str, FixtureBundle] = {}


def fixtures_dir(override: str | None = None) -> Path:
    base = override or os.environ.get("PE_FIXTURES_DIR") or DEFAULT_FIXTURES_DIR
    return Path(base)


def load_bundle(name: str, *, override_dir: str | None = None) -> FixtureBundle:
    """Load and cache a fixture bundle by name (without the .json suffix).

    Raises FixtureError if the file is missing or malformed.
    """
    cache_key = (override_dir or "", name)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    directory = fixtures_dir(override_dir)
    path = directory / (name + ".json")
    if not path.is_file():
        raise FixtureError("fixture bundle not found: " + name)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise FixtureError(
            "fixture bundle " + name + " is malformed: " + str(exc)
        ) from exc

    if not isinstance(raw, dict):
        raise FixtureError("fixture bundle " + name + " must be a JSON object")

    bundle = _coerce_bundle(name, raw)
    _CACHE[cache_key] = bundle
    return bundle


def _coerce_bundle(name: str, raw: dict[str, Any]) -> FixtureBundle:
    language = raw.get("language", "ko")
    if language not in ("ko", "en"):
        raise FixtureError("fixture " + name + " has an unsupported language")

    input_text = raw.get("input_text", "")
    if not isinstance(input_text, str) or not input_text.strip():
        raise FixtureError("fixture " + name + " has empty input_text")

    prohibited = raw.get("prohibited_inventions", [])
    if not isinstance(prohibited, list):
        raise FixtureError(
            "fixture " + name + " prohibited_inventions must be a list"
        )

    allowed = raw.get("allowed_facts", [])
    if not isinstance(allowed, list):
        raise FixtureError(
            "fixture " + name + " allowed_facts must be a list"
        )

    return FixtureBundle(
        name=name,
        language=language,
        input_text=input_text,
        prohibited_inventions=tuple(prohibited),
        allowed_facts=tuple(allowed),
        plan_payload=raw.get("plan_payload"),
        draft_payload=raw.get("draft_payload"),
        follow_up_plan_payload=raw.get("follow_up_plan_payload"),
        follow_up_draft_payload=raw.get("follow_up_draft_payload"),
        feedback_directions=tuple(raw.get("feedback_directions", [])),
        feedback_free_text=raw.get("feedback_free_text"),
        notes=raw.get("notes", {}),
    )


def list_bundles(override_dir: str | None = None) -> list[str]:
    """Return the sorted names of all available fixture bundles."""
    directory = fixtures_dir(override_dir)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


_FEEDBACK_ID_PLACEHOLDER = "__FEEDBACK_ID__"


def inject_feedback_id(payload: Any, feedback_id: str) -> Any:
    """Recursively replace the feedback-id placeholder in a payload.

    Follow-up plan/draft payloads use a placeholder because the real feedback_id
    is a UUID generated at runtime. This helper walks the payload and replaces
    every occurrence of the placeholder string with the real id.
    """
    if isinstance(payload, str):
        return feedback_id if payload == _FEEDBACK_ID_PLACEHOLDER else payload
    if isinstance(payload, list):
        return [inject_feedback_id(item, feedback_id) for item in payload]
    if isinstance(payload, dict):
        return {
            key: inject_feedback_id(value, feedback_id)
            for key, value in payload.items()
        }
    return payload
