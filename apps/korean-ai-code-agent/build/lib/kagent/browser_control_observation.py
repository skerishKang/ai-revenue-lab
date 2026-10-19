"""#3629 — agent-side bounded page-observation authority (owner decision #3609).

The Desktop trusted main owns extraction and projects through its own bounded
contract; this module is the agent-side authority for the bounded observation
it may receive. It validates the projection *exactly* — the same bounds the
D1=ENABLED_BOUNDED decision fixed:

    MAX_ELEMENTS=400  MAX_SERIALIZED_BYTES=8192  NAME_MAX_CHARS=64
    CREDENTIAL_FIELDS=MASKED_ONLY

and refuses everything else fail-closed. Raw DOM, raw HTML, page source,
screenshots, PDF, cookies, localStorage, sessionStorage, password values, form
values, textarea contents, arbitrary attributes, raw href/query material and
JavaScript evaluation results are structurally unrepresentable: an exact-key
schema is the enforcement and the forbidden-key list is the explicit refusal
vocabulary. Over-budget projections fail closed here — truncation is the
trusted host's job, and the agent surface must never widen it.

    BROWSER_CONTROL_OBSERVATION_IMPLEMENTED = True
    BROWSER_ACTION_EXECUTION_IMPLEMENTED = False   (click/type/select/scroll: next child)
    TRUSTED_MAIN_HOST_OWNS_EXTRACTION = True
    RENDERER_OWNS_PROJECTION_AUTHORITY = False
    GENERIC_IPC_SURFACE = False

Site/origin scope, leases and step-up approval remain owned by the #3607
decision family. No lease execution, no action, no transport and no Production
mutation exists in this slice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ContractError

BROWSER_OBSERVATION_HOST_REF = "desktop-trusted-main-observation@1"
MAX_OBSERVATION_ELEMENTS = 400
MAX_SERIALIZED_OBSERVATION_BYTES = 8192
MAX_ELEMENT_NAME_CHARS = 64
MAX_ORIGIN_CHARS = 255
MASKED_CREDENTIAL_NAME = "[credential]"
BROWSER_SITE_SCOPE_POLICY_OWNER = "#3607"

BROWSER_CONTROL_OBSERVATION_IMPLEMENTED = True
BROWSER_ACTION_EXECUTION_IMPLEMENTED = False
TRUSTED_MAIN_HOST_OWNS_EXTRACTION = True
RENDERER_OWNS_PROJECTION_AUTHORITY = False
SECOND_BROWSER_AUTHORITY = False
GENERIC_IPC_SURFACE = False
JAVASCRIPT_EVALUATE_PERMITTED = False
SCREENSHOT_SUPPORTED = False
PDF_CAPTURE_SUPPORTED = False
COOKIE_STORAGE_EXPORT_SUPPORTED = False
CREDENTIAL_VALUE_EXPORT_SUPPORTED = False

PROJECTION_ID_RE = re.compile(r"^obs_[0-9a-f]{24}$")
ELEMENT_REF_RE = re.compile(r"^el-\d{4}$")
ORIGIN_RE = re.compile(
    r"^https://[a-z0-9.-]+(?::\d{1,5})?$|^http://[a-z0-9.-]+(?::\d{1,5})?$"
)
MAX_BOUNDS_MAGNITUDE = 10_000_000

#: Page-derived / secret material that may never appear on this surface.
FORBIDDEN_ELEMENT_KEYS = frozenset(
    {
        "value",
        "values",
        "text",
        "content",
        "html",
        "dom",
        "source",
        "screenshot",
        "image",
        "pdf",
        "attributes",
        "href",
        "src",
        "form_values",
        "formValues",
        "cookies",
        "local_storage",
        "localStorage",
        "session_storage",
        "sessionStorage",
    }
)

ELEMENT_KEYS = frozenset(
    {
        "element_ref",
        "role",
        "name",
        "bounds",
        "state_flags",
        "interaction_flags",
        "credential_field",
    }
)

OBSERVATION_KEYS = frozenset(
    {
        "projection_id",
        "host_ref",
        "origin_ref",
        "element_count",
        "omitted_elements",
        "truncated",
        "elements",
        "page_content_included",
        "cookie_included",
        "credential_value_included",
        "dom_api_exposed",
    }
)

ROLE_ALLOWLIST = frozenset(
    {
        "button",
        "link",
        "textbox",
        "textarea",
        "searchbox",
        "combobox",
        "checkbox",
        "radio",
        "switch",
        "slider",
        "spinbutton",
        "option",
        "tab",
        "menuitem",
        "listbox",
        "treeitem",
        "dialog",
        "alertdialog",
        "heading",
        "label",
        "statictext",
        "image",
        "list",
        "listitem",
        "table",
        "row",
        "cell",
        "group",
        "navigation",
        "main",
        "form",
        "progressbar",
        "status",
        "toolbar",
        "menubar",
    }
)

STATE_FLAG_ALLOWLIST = frozenset(
    {
        "disabled",
        "focused",
        "focusable",
        "required",
        "readonly",
        "selected",
        "checked",
        "unchecked",
        "mixed",
        "expanded",
        "collapsed",
        "pressed",
        "invalid",
        "busy",
        "multiline",
        "multiselectable",
    }
)

INTERACTION_FLAG_ALLOWLIST = frozenset(
    {
        "clickable",
        "typeable",
        "selectable",
        "toggleable",
        "expandable",
        "scrollable",
        "editable",
    }
)


class BrowserObservationRefusal(ContractError):
    """Fail-closed refusal carrying a stable, user-projectable code."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def truncate_observation_name(name: str) -> str:
    """Bounded deterministic name truncation (Python strings are code points)."""
    return name[:MAX_ELEMENT_NAME_CHARS]


def observation_element_ref(sequence: int) -> str:
    """Stable per-snapshot element ref, derived from document order only."""
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 1 <= sequence <= MAX_OBSERVATION_ELEMENTS:
        raise BrowserObservationRefusal(
            "contract_violation", "element ref sequence must be within the projection bounds"
        )
    return f"el-{sequence:04d}"


@dataclass(frozen=True, slots=True)
class BoundedObservationElement:
    element_ref: str
    role: str
    name: str
    bounds: tuple[int, int, int, int]
    state_flags: tuple[str, ...]
    interaction_flags: tuple[str, ...]
    credential_field: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "element_ref": self.element_ref,
            "role": self.role,
            "name": self.name,
            "bounds": {
                "x": self.bounds[0],
                "y": self.bounds[1],
                "width": self.bounds[2],
                "height": self.bounds[3],
            },
            "state_flags": list(self.state_flags),
            "interaction_flags": list(self.interaction_flags),
            "credential_field": self.credential_field,
        }


@dataclass(frozen=True, slots=True)
class BoundedPageObservation:
    projection_id: str
    origin_ref: str
    elements: tuple[BoundedObservationElement, ...]
    omitted_elements: int
    truncated: bool

    def safe_dict(self) -> dict[str, Any]:
        """The only external projection shape; fail-closed flags are pinned here."""
        return {
            "projection_id": self.projection_id,
            "host_ref": BROWSER_OBSERVATION_HOST_REF,
            "origin_ref": self.origin_ref,
            "element_count": len(self.elements),
            "omitted_elements": self.omitted_elements,
            "truncated": self.truncated,
            "elements": [element.safe_dict() for element in self.elements],
            "page_content_included": False,
            "cookie_included": False,
            "credential_value_included": False,
            "dom_api_exposed": False,
        }

    def serialized_bytes(self) -> int:
        return len(_canonical_json(self.safe_dict()).encode("utf-8"))


def _refuse(message: str) -> None:
    raise BrowserObservationRefusal("contract_violation", message)


def _validate_flag_list(value: Any, allowlist: frozenset[str], field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(flag, str) or flag not in allowlist for flag in value
    ):
        _refuse(f"{field} must be a list of bounded allowlisted flags")
    return tuple(sorted(set(value)))  # type: ignore[arg-type]


def _validate_element(raw: Any, sequence: int) -> BoundedObservationElement:
    if not isinstance(raw, Mapping):
        _refuse("observation element must be an object")
    assert isinstance(raw, Mapping)
    for key in raw:
        if key in FORBIDDEN_ELEMENT_KEYS:
            _refuse(f"observation element carries forbidden page-derived key {key!r}")
        if key not in ELEMENT_KEYS:
            _refuse(f"observation element carries an unknown key {key!r}")
    missing = ELEMENT_KEYS - set(raw)
    if missing:
        _refuse(f"observation element is missing bounded keys: {sorted(missing)!r}")

    element_ref = raw["element_ref"]
    if not isinstance(element_ref, str) or not ELEMENT_REF_RE.fullmatch(element_ref):
        _refuse("element_ref must be a bounded el-NNNN reference")
    if element_ref != observation_element_ref(sequence):
        _refuse("element_ref must follow document order")

    role = raw["role"]
    if not isinstance(role, str) or role not in ROLE_ALLOWLIST:
        _refuse("role must be within the bounded allowlist")

    credential_field = raw["credential_field"]
    if not isinstance(credential_field, bool):
        _refuse("credential_field must be a boolean")
    name = raw["name"]
    if not isinstance(name, str):
        _refuse("name must be a string")
    if credential_field:
        # Credential-sensitive controls exist only as the masked marker: the
        # accessible name never carries the typed value on this surface.
        if name != MASKED_CREDENTIAL_NAME:
            _refuse("credential field must project the masked marker as its name")
    elif len(name) > MAX_ELEMENT_NAME_CHARS:
        _refuse("name must be at most 64 characters")

    bounds = raw["bounds"]
    if not isinstance(bounds, Mapping) or set(bounds) != {"x", "y", "width", "height"}:
        _refuse("bounds must carry exactly x, y, width and height")
    numbers: list[int] = []
    for axis in ("x", "y", "width", "height"):
        entry = bounds[axis]
        if isinstance(entry, bool) or not isinstance(entry, int) or abs(entry) > MAX_BOUNDS_MAGNITUDE:
            _refuse("bounds entries must be bounded integers")
        numbers.append(entry)
    if numbers[2] < 0 or numbers[3] < 0:
        _refuse("bounds width and height must be non-negative")

    return BoundedObservationElement(
        element_ref=element_ref,
        role=role,
        name=name,
        bounds=(numbers[0], numbers[1], numbers[2], numbers[3]),
        state_flags=_validate_flag_list(raw["state_flags"], STATE_FLAG_ALLOWLIST, "state_flags"),
        interaction_flags=_validate_flag_list(
            raw["interaction_flags"], INTERACTION_FLAG_ALLOWLIST, "interaction_flags"
        ),
        credential_field=credential_field,
    )


def validate_trusted_page_observation(payload: Mapping[str, Any]) -> BoundedPageObservation:
    """Validate one inbound trusted-main observation, fail-closed and exact.

    The renderer owns no projection authority: the pinned ``host_ref`` is the
    schema-level half of the trust boundary (the process boundary — no renderer
    channel exists on this surface — is the other half). Every derived flag is
    re-checked here and the byte budget is re-enforced against this surface's
    own canonical serialization.
    """

    if not isinstance(payload, Mapping):
        _refuse("observation must be an object")
    assert isinstance(payload, Mapping)
    for key in payload:
        if key not in OBSERVATION_KEYS:
            _refuse(f"observation carries an unknown key {key!r}")
    missing = OBSERVATION_KEYS - set(payload)
    if missing:
        _refuse(f"observation is missing bounded keys: {sorted(missing)!r}")

    projection_id = payload["projection_id"]
    if not isinstance(projection_id, str) or not PROJECTION_ID_RE.fullmatch(projection_id):
        _refuse("projection_id must be obs_ plus 24 lowercase hex characters")
    if payload["host_ref"] != BROWSER_OBSERVATION_HOST_REF:
        raise BrowserObservationRefusal(
            "trusted_host_required", "observation did not come from the trusted main host"
        )

    origin_ref = payload["origin_ref"]
    if not isinstance(origin_ref, str):
        _refuse("origin_ref must be a string")
    origin = origin_ref.strip().lower()
    # Origin only: path/query/userinfo material — where secrets live — is refused.
    if len(origin) > MAX_ORIGIN_CHARS:
        _refuse(f"origin_ref must be at most {MAX_ORIGIN_CHARS} characters")
    if not ORIGIN_RE.fullmatch(origin):
        _refuse("origin_ref must be a bare http(s) origin without path, query or credentials")

    for flag in (
        "page_content_included",
        "cookie_included",
        "credential_value_included",
        "dom_api_exposed",
    ):
        if payload[flag] is not False:
            _refuse(f"{flag} is pinned to False on this surface")
    truncated = payload["truncated"]
    if not isinstance(truncated, bool):
        _refuse("truncated must be a boolean")
    omitted_elements = payload["omitted_elements"]
    if (
        isinstance(omitted_elements, bool)
        or not isinstance(omitted_elements, int)
        or omitted_elements < 0
    ):
        _refuse("omitted_elements must be a non-negative integer")

    raw_elements = payload["elements"]
    if not isinstance(raw_elements, list):
        _refuse("elements must be a list")
    if len(raw_elements) > MAX_OBSERVATION_ELEMENTS:
        _refuse(f"observation may carry at most {MAX_OBSERVATION_ELEMENTS} elements")
    elements = tuple(
        _validate_element(raw, sequence) for sequence, raw in enumerate(raw_elements, start=1)
    )
    if payload["element_count"] != len(elements):
        _refuse("element_count must match the projected elements")

    observation = BoundedPageObservation(
        projection_id=projection_id,
        origin_ref=origin,
        elements=elements,
        omitted_elements=omitted_elements,
        truncated=truncated,
    )
    if observation.serialized_bytes() > MAX_SERIALIZED_OBSERVATION_BYTES:
        raise BrowserObservationRefusal(
            "projection_exceeds_byte_budget",
            f"bounded observation exceeds {MAX_SERIALIZED_OBSERVATION_BYTES} serialized bytes",
        )
    return observation


def build_bounded_page_observation(
    projection_id: str,
    origin: str,
    elements: list[dict[str, Any]],
    omitted_elements: int = 0,
) -> dict[str, Any]:
    """Project trusted-host material into the exact agent-facing wire shape.

    Mirrors the Desktop host contract: deterministic document-order projection
    with derived element refs, credential masking, and the byte budget enforced
    by deterministic whole-element truncation (fail-closed never cuts bytes).
    """

    if not isinstance(projection_id, str) or not PROJECTION_ID_RE.fullmatch(projection_id):
        raise BrowserObservationRefusal(
            "contract_violation", "projection_id must be obs_ plus 24 lowercase hex characters"
        )
    origin_ref = (origin or "").strip().lower()
    if len(origin_ref) > MAX_ORIGIN_CHARS or not ORIGIN_RE.fullmatch(origin_ref):
        raise BrowserObservationRefusal(
            "contract_violation", "origin must be a bounded bare http(s) origin"
        )
    projected: list[dict[str, Any]] = []
    source_keys = {
        "role",
        "name",
        "bounds",
        "state_flags",
        "interaction_flags",
        "credential_field",
    }
    for raw in elements:
        if not isinstance(raw, Mapping):
            _refuse("source element must be an object")
        assert isinstance(raw, Mapping)
        for key in raw:
            if key in FORBIDDEN_ELEMENT_KEYS:
                _refuse(f"source element carries forbidden page-derived key {key!r}")
            if key not in source_keys:
                _refuse(f"source element carries an unknown key {key!r}")
        missing = source_keys - set(raw)
        if missing:
            _refuse(f"source element is missing bounded keys: {sorted(missing)!r}")
        if len(projected) >= MAX_OBSERVATION_ELEMENTS:
            break
        role = raw["role"]
        credential_field = raw["credential_field"]
        name = MASKED_CREDENTIAL_NAME if credential_field else truncate_observation_name(raw["name"])
        sequence = len(projected) + 1
        projected.append(
            {
                "element_ref": observation_element_ref(sequence),
                "role": role,
                "name": name,
                "bounds": dict(raw["bounds"]),
                "state_flags": sorted(set(raw["state_flags"])),
                "interaction_flags": sorted(set(raw["interaction_flags"])),
                "credential_field": bool(credential_field),
            }
        )
    classified = len(projected)
    truncated = len(elements) - omitted_elements > classified
    payload: dict[str, Any] = {
        "projection_id": projection_id,
        "host_ref": BROWSER_OBSERVATION_HOST_REF,
        "origin_ref": origin_ref,
        "element_count": classified,
        "omitted_elements": omitted_elements,
        "truncated": truncated,
        "elements": projected,
        "page_content_included": False,
        "cookie_included": False,
        "credential_value_included": False,
        "dom_api_exposed": False,
    }
    encoded = _canonical_json(payload).encode("utf-8")
    while len(encoded) > MAX_SERIALIZED_OBSERVATION_BYTES and payload["elements"]:
        payload["elements"].pop()
        payload["element_count"] = len(payload["elements"])
        payload["truncated"] = True
        truncated = True
        encoded = _canonical_json(payload).encode("utf-8")
    if len(encoded) > MAX_SERIALIZED_OBSERVATION_BYTES:
        raise BrowserObservationRefusal(
            "projection_exceeds_byte_budget",
            f"bounded observation exceeds {MAX_SERIALIZED_OBSERVATION_BYTES} serialized bytes",
        )
    return payload
