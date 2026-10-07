"""#3647 — bounded browser.control action slice 1 (agent-side authority).

Implements the #3607 approval-granularity design for the **lease-eligible
first slice only**, on top of the #3629 bounded observation authority and the
#3609 D1=ENABLED_BOUNDED decision:

    lease-eligible: scroll / focus / click / type / select
    step-up required (refused here): submit, download, upload, clipboard
        read/write, open/close tab, cross-origin navigation, credential-field
        interaction, payment, account/security change, permission prompts,
        external protocol launch, destructive actions
    prohibited (structurally absent): javascript_evaluate, raw DOM read

No new approval or browser authority exists here: the lease shape follows the
#3607 frozen design (one origin, explicit action classes, bounded action
count, TTL inside the reviewed grant-family limits, no cross-run transfer)
and the canonical P01 approval + durable one-shot admission is the next
slice's port. Bounded observation cannot distinguish a submit button from a
safe one (arbitrary attributes are banned from the projection), so button-role
clicks default to step-up refusal; typing is single-line non-credential text
via input synthesis (no keystroke injection, no page-derived material).

    BROWSER_ACTION_EXECUTION_IMPLEMENTED = True   (lease-eligible slice only)
    STEP_UP_EXECUTION_IMPLEMENTED = False
    JAVASCRIPT_EVALUATE_PERMITTED = False
    GENERIC_IPC_SURFACE = False
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import ContractError

BROWSER_ACTION_SESSION_REF = "browser-control-action@1"

LEASE_ELIGIBLE_ACTIONS = ("scroll", "focus", "click", "type", "select")
STEP_UP_REQUIRED_ACTIONS = (
    "submit",
    "download",
    "upload",
    "clipboard_read",
    "clipboard_write",
    "open_new_tab",
    "close_tab",
    "cross_origin_navigation",
    "credential_field_interaction",
    "payment_or_purchase",
    "account_or_security_change",
    "permission_prompt",
    "external_protocol_launch",
    "destructive_action",
)
PROHIBITED_ACTIONS = ("javascript_evaluate", "observe_dom_read")

BROWSER_ACTION_EXECUTION_IMPLEMENTED = True
STEP_UP_EXECUTION_IMPLEMENTED = False
JAVASCRIPT_EVALUATE_PERMITTED = False
GENERIC_IPC_SURFACE = False
SECOND_BROWSER_AUTHORITY = False
NEW_APPROVAL_STORE = False
DURABLE_ADMISSION_WIRED = False

MAX_ACTION_TEXT_CHARS = 256
MAX_SCROLL_DELTA = 10_000
MAX_SELECT_INDEX = 1023
MAX_SERIALIZED_ACTION_BYTES = 2048
MAX_ACTIONS_PER_LEASE = 64
MAX_LEASE_TTL_SECONDS = 900
MIN_LEASE_TTL_SECONDS = 60
MAX_ORIGIN_CHARS = 255

ACTION_ID_RE = re.compile(r"^act_[0-9a-f]{24}$")
ELEMENT_REF_RE = re.compile(r"^el-\d{4}$")
ORIGIN_RE = re.compile(
    r"^https://[a-z0-9.-]+(?::\d{1,5})?$|^http://[a-z0-9.-]+(?::\d{1,5})?$"
)
SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")

#: Roles a bounded click/focus may target in slice 1. Buttons are excluded on
#: purpose: the projection cannot tell submit from safe, so they step up.
CLICKABLE_ROLE_ALLOWLIST = frozenset(
    {"link", "tab", "menuitem", "treeitem", "checkbox", "radio", "switch", "option"}
)
TYPEABLE_ROLE_ALLOWLIST = frozenset(
    {"textbox", "textarea", "searchbox", "combobox", "spinbutton"}
)
SELECT_ROLE_ALLOWLIST = frozenset({"listbox", "combobox"})

ACTION_PARAMS_KEYS = frozenset({"dx", "dy", "text", "option_index"})
ACTION_REQUEST_KEYS = frozenset({"action", "element_ref", "session_ref", "origin_ref", "params"})
ACTION_LEASE_KEYS = frozenset(
    {
        "lease_id",
        "session_ref",
        "origin_ref",
        "allowed_actions",
        "max_actions",
        "issued_at",
        "expires_at",
    }
)
ACTION_RECEIPT_KEYS = frozenset(
    {
        "action_id",
        "action",
        "element_ref",
        "origin_ref",
        "outcome",
        "page_content_included",
        "cookie_included",
        "credential_value_included",
        "dom_api_exposed",
    }
)


class BrowserControlActionRefusal(ContractError):
    """Fail-closed refusal carrying a stable, user-projectable code."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def classify_browser_control_action(action: str) -> str:
    """Map one action name to lease_eligible | step_up_required | prohibited."""
    if action in LEASE_ELIGIBLE_ACTIONS:
        return "lease_eligible"
    if action in STEP_UP_REQUIRED_ACTIONS:
        return "step_up_required"
    if action in PROHIBITED_ACTIONS:
        return "prohibited"
    raise BrowserControlActionRefusal("unknown_action", "unknown browser control action")


def _refuse(message: str) -> None:
    raise BrowserControlActionRefusal("contract_violation", message)


def _aware(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _refuse(f"{field} must be timezone-aware")
    assert isinstance(value, datetime)
    return value.astimezone(timezone.utc)


def _origin(value: Any, field: str) -> str:
    if not isinstance(value, str):
        _refuse(f"{field} must be a string")
    origin = value.strip().lower()
    if len(origin) > MAX_ORIGIN_CHARS or not ORIGIN_RE.fullmatch(origin):
        _refuse(f"{field} must be a bounded bare http(s) origin")
    return origin


def _ref(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_REF_RE.fullmatch(value.strip()):
        _refuse(f"{field} must be a bounded safe reference")
    return value.strip()


@dataclass(frozen=True, slots=True)
class BrowserControlActionRequest:
    """One bounded action request. Only lease-eligible classes validate here."""

    action: str
    session_ref: str
    origin_ref: str
    element_ref: str | None = None
    params: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        classification = classify_browser_control_action(self.action)
        if classification != "lease_eligible":
            raise BrowserControlActionRefusal(
                "step_up_required" if classification == "step_up_required" else "action_prohibited",
                f"action {self.action!r} is not part of the lease-eligible slice",
            )
        object.__setattr__(self, "session_ref", _ref(self.session_ref, "session_ref"))
        object.__setattr__(self, "origin_ref", _origin(self.origin_ref, "origin_ref"))

        if self.action == "scroll":
            if self.element_ref is not None:
                _refuse("scroll targets the viewport and must not carry an element_ref")
            params = self.params or {}
            if not isinstance(params, Mapping) or set(params) != {"dx", "dy"}:
                _refuse("scroll params must carry exactly dx and dy")
            for axis in ("dx", "dy"):
                entry = params.get(axis, 0)
                if isinstance(entry, bool) or not isinstance(entry, int) or abs(entry) > MAX_SCROLL_DELTA:
                    _refuse(f"scroll {axis} must be a bounded integer")
        elif self.action in ("focus", "click"):
            if self.params:
                _refuse(f"{self.action} carries no params")
            if not isinstance(self.element_ref, str) or not ELEMENT_REF_RE.fullmatch(self.element_ref):
                _refuse(f"{self.action} requires a bounded element_ref")
        elif self.action == "type":
            if not isinstance(self.element_ref, str) or not ELEMENT_REF_RE.fullmatch(self.element_ref):
                _refuse("type requires a bounded element_ref")
            params = self.params or {}
            if not isinstance(params, Mapping) or set(params) != {"text"}:
                _refuse("type params must carry exactly text")
            text = params["text"]
            if not isinstance(text, str) or not 1 <= len(text) <= MAX_ACTION_TEXT_CHARS:
                _refuse(f"type text must be 1..{MAX_ACTION_TEXT_CHARS} characters")
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
                # CR/LF would submit forms; other control bytes have no place
                # in non-sensitive typing. Input synthesis never needs them.
                _refuse("type text must not contain control characters")
        elif self.action == "select":
            if not isinstance(self.element_ref, str) or not ELEMENT_REF_RE.fullmatch(self.element_ref):
                _refuse("select requires a bounded element_ref")
            params = self.params or {}
            if not isinstance(params, Mapping) or set(params) != {"option_index"}:
                _refuse("select params must carry exactly option_index")
            index = params["option_index"]
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= MAX_SELECT_INDEX:
                _refuse(f"select option_index must be 0..{MAX_SELECT_INDEX}")

    def safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": self.action,
            "session_ref": self.session_ref,
            "origin_ref": self.origin_ref,
            "element_ref": self.element_ref,
            "params": dict(self.params) if self.params else {},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_SERIALIZED_ACTION_BYTES:
            raise BrowserControlActionRefusal(
                "contract_violation", "bounded action request exceeds the serialization budget"
            )
        return payload


@dataclass(frozen=True, slots=True)
class BrowserControlActionLease:
    """The #3607 bounded lease shape for slice 1 (validation authority).

    One origin, explicit action classes, bounded action count, TTL inside the
    reviewed grant-family limits, non-transferable. The canonical P01 approval
    and the durable one-shot admission plug in through the next slice's port;
    this slice creates no second approval store.
    """

    lease_id: str
    session_ref: str
    origin_ref: str
    allowed_actions: tuple[str, ...]
    max_actions: int
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", _ref(self.lease_id, "lease_id"))
        object.__setattr__(self, "session_ref", _ref(self.session_ref, "session_ref"))
        object.__setattr__(self, "origin_ref", _origin(self.origin_ref, "origin_ref"))
        actions = tuple(self.allowed_actions)
        if not actions:
            _refuse("lease must allow at least one bounded action")
        if any(classify_browser_control_action(entry) != "lease_eligible" for entry in actions):
            _refuse("lease allowed_actions must be lease-eligible only")
        object.__setattr__(self, "allowed_actions", tuple(sorted(set(actions))))
        if (
            isinstance(self.max_actions, bool)
            or not isinstance(self.max_actions, int)
            or not 1 <= self.max_actions <= MAX_ACTIONS_PER_LEASE
        ):
            _refuse(f"lease max_actions must be 1..{MAX_ACTIONS_PER_LEASE}")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        lifetime = (expires - issued).total_seconds()
        if not MIN_LEASE_TTL_SECONDS <= lifetime <= MAX_LEASE_TTL_SECONDS:
            _refuse(
                f"lease lifetime must be between {MIN_LEASE_TTL_SECONDS} and "
                f"{MAX_LEASE_TTL_SECONDS} seconds"
            )
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def allows(self, request: BrowserControlActionRequest) -> bool:
        return (
            request.action in self.allowed_actions
            and request.origin_ref == self.origin_ref
            and request.session_ref == self.session_ref
        )


def validate_bounded_action_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one inbound action receipt: exact keys, pinned false flags."""

    if not isinstance(payload, Mapping):
        _refuse("action receipt must be an object")
    assert isinstance(payload, Mapping)
    for key in payload:
        if key not in ACTION_RECEIPT_KEYS:
            _refuse(f"action receipt carries an unknown key {key!r}")
    missing = ACTION_RECEIPT_KEYS - set(payload)
    if missing:
        _refuse(f"action receipt is missing bounded keys: {sorted(missing)!r}")
    if not isinstance(payload["action_id"], str) or not ACTION_ID_RE.fullmatch(payload["action_id"]):
        _refuse("action_id must be act_ plus 24 lowercase hex characters")
    if classify_browser_control_action(payload["action"]) != "lease_eligible":
        _refuse("receipt action must be lease-eligible")
    element_ref = payload["element_ref"]
    if element_ref is not None and (
        not isinstance(element_ref, str) or not ELEMENT_REF_RE.fullmatch(element_ref)
    ):
        _refuse("element_ref must be a bounded el-NNNN reference or null")
    _origin(payload["origin_ref"], "origin_ref")
    if payload["outcome"] != "dispatched":
        _refuse("slice 1 receipts only record dispatched outcomes")
    for flag in (
        "page_content_included",
        "cookie_included",
        "credential_value_included",
        "dom_api_exposed",
    ):
        if payload[flag] is not False:
            _refuse(f"{flag} is pinned to False on this surface")
    return dict(payload)
