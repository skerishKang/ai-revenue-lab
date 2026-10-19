"""#3647 — bounded browser.control action slice 1 (agent-side authority).

Source of truth: the #3607 CENTRAL final design disposition
(BOUNDED_HYBRID_LEASE_PLUS_STEP_UP), applied on top of the #3629 bounded
observation authority and the #3609 D1=ENABLED_BOUNDED decision.

Lease policy (authoritative values, never redefined):

    LEASE_TTL_SECONDS=300          canonical issuance default
    LEASE_TTL_MAX_SECONDS=900      hard max
    LEASE_MAX_ACTIONS=25           canonical issuance default
    LEASE_MAX_ACTIONS_HARD_CAP=100
    LEASE_IDLE_SECONDS=120
    LEASE_SITE_SCOPE=EXACT_ORIGIN_MAX_3_NO_WILDCARD
    SLICE1_ORIGIN_SCOPE=EXACT_ONE_ORIGIN   (deliberate slice-1 tightening)
    LEASE_CROSS_ORIGIN_POLICY=INVALIDATE_AND_REQUIRE_STEP_UP
    LEASE_RUN_TRANSFER=PROHIBITED
    LEASE_REVOCATION=IMMEDIATE_USER_VISIBLE

Action taxonomy (#3607 effect class first, verb second):

    LEASE_ALLOWED      bounded non-committing interaction only; a role is
                       lease-allowed only where the #3629 projection can prove
                       it (click is restricted to tab/treeitem roles);
    STEP_UP_REQUIRED   submit, credential_field_interaction, upload, download
                       (download additionally EXECUTION_BLOCKED until the
                       artifact/filesystem.write authority exists),
                       clipboard_read/write, cross_origin_navigation;
    PROHIBITED         javascript_evaluate, payment_or_purchase,
                       account_or_security_change, destructive_action,
                       permission_prompt;
    OUT_OF_SCOPE       external_protocol_launch, OS Computer Use, the generic
                       CDP/DevTools surface, file: navigation.

No new approval or browser authority exists here: the lease carries the full
#3607 correlation set (request fingerprint, browser session, owner/workspace/
run, exact action classes, exact origin scope, bounded action count, expiry,
P01 approval/evidence refs) and the canonical durable admission that mints it
is NOT wired in this slice — nothing mints, refreshes, stores or replays a
lease, and no second approval store exists.

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
    "credential_field_interaction",
    "upload",
    "download",
    "clipboard_read",
    "clipboard_write",
    "cross_origin_navigation",
)
PROHIBITED_ACTIONS = (
    "javascript_evaluate",
    "payment_or_purchase",
    "account_or_security_change",
    "destructive_action",
    "permission_prompt",
)
OUT_OF_SCOPE_ACTIONS = ("external_protocol_launch",)
OUT_OF_SCOPE_SURFACES = (
    "os_computer_use",
    "generic_cdp_devtools_surface",
    "file_navigation",
)

BROWSER_ACTION_EXECUTION_IMPLEMENTED = True
STEP_UP_EXECUTION_IMPLEMENTED = False
JAVASCRIPT_EVALUATE_PERMITTED = False
GENERIC_IPC_SURFACE = False
SECOND_BROWSER_AUTHORITY = False
NEW_APPROVAL_STORE = False
DURABLE_ADMISSION_WIRED = False

# #3607 authoritative lease values.
LEASE_TTL_SECONDS = 300
LEASE_TTL_MAX_SECONDS = 900
LEASE_MAX_ACTIONS = 25
LEASE_MAX_ACTIONS_HARD_CAP = 100
LEASE_IDLE_SECONDS = 120
LEASE_SITE_SCOPE_POLICY = "EXACT_ORIGIN_MAX_3_NO_WILDCARD"
LEASE_CROSS_ORIGIN_POLICY = "INVALIDATE_AND_REQUIRE_STEP_UP"
LEASE_RUN_TRANSFER = "PROHIBITED"
LEASE_REVOCATION = "IMMEDIATE_USER_VISIBLE"
SLICE1_ORIGIN_SCOPE = "EXACT_ONE_ORIGIN"
DOWNLOAD_EXECUTION_BLOCKED_UNTIL_ARTIFACT_AUTHORITY = True

MAX_ACTION_TEXT_CHARS = 256
MAX_SCROLL_DELTA = 10_000
MAX_SELECT_INDEX = 1023
MAX_SERIALIZED_ACTION_BYTES = 2048
MAX_ORIGIN_CHARS = 255

ACTION_ID_RE = re.compile(r"^act_[0-9a-f]{24}$")
ELEMENT_REF_RE = re.compile(r"^el-\d{4}$")
ORIGIN_RE = re.compile(
    r"^https://[a-z0-9.-]+(?::\d{1,5})?$|^http://[a-z0-9.-]+(?::\d{1,5})?$"
)
SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")

#: Roles where the #3629 projection can actually prove non-committing
#: interaction. Everything else — link (href invisible), button (submit
#: indistinguishable), menuitem/checkbox/radio/switch/option (durable or
#: external effect not disprovable) — steps up. Effect class first, verb
#: second; no new observation attribute was invented for this.
CLICK_ALLOWED_ROLE_ALLOWLIST = frozenset({"tab", "treeitem"})
TYPEABLE_ROLE_ALLOWLIST = frozenset(
    {"textbox", "textarea", "searchbox", "combobox", "spinbutton"}
)
SELECT_ROLE_ALLOWLIST = frozenset({"listbox", "combobox"})

ACTION_REQUEST_KEYS = frozenset(
    {
        "action",
        "element_ref",
        "browser_session_ref",
        "origin_ref",
        "params",
    }
)
ACTION_LEASE_KEYS = frozenset(
    {
        "lease_id",
        "request_fingerprint",
        "browser_session_ref",
        "run_ref",
        "workspace_ref",
        "owner_ref",
        "allowed_action_classes",
        "origin_scope",
        "max_actions",
        "issued_at",
        "expires_at",
        "approval_ref",
        "evidence_ref",
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
    """Map one action name to lease_eligible | step_up_required | prohibited | out_of_scope."""
    if action in LEASE_ELIGIBLE_ACTIONS:
        return "lease_eligible"
    if action in STEP_UP_REQUIRED_ACTIONS:
        return "step_up_required"
    if action in PROHIBITED_ACTIONS:
        return "prohibited"
    if action in OUT_OF_SCOPE_ACTIONS:
        return "out_of_scope"
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
    browser_session_ref: str
    origin_ref: str
    element_ref: str | None = None
    params: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        classification = classify_browser_control_action(self.action)
        if classification != "lease_eligible":
            raise BrowserControlActionRefusal(
                "step_up_required"
                if classification == "step_up_required"
                else "action_prohibited" if classification == "prohibited" else "out_of_scope",
                f"action {self.action!r} is not part of the lease-eligible slice",
            )
        object.__setattr__(
            self, "browser_session_ref", _ref(self.browser_session_ref, "browser_session_ref")
        )
        object.__setattr__(self, "origin_ref", _origin(self.origin_ref, "origin_ref"))

        if self.action == "scroll":
            if self.element_ref is not None:
                _refuse("scroll targets the viewport and must not carry an element_ref")
            params = self.params or {}
            if not isinstance(params, Mapping) or set(params) != {"dx", "dy"}:
                _refuse("scroll params must carry exactly dx and dy")
            for axis in ("dx", "dy"):
                entry = params.get(axis)
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
            "browser_session_ref": self.browser_session_ref,
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
    """The #3607 bounded lease shape for slice 1 (validation authority only).

    Carries the full correlation set and never mints, refreshes, stores or
    replays a lease: the canonical P01 approval + durable admission that mints
    it is the next slice's fail-closed port, and no second approval store
    exists here.
    """

    lease_id: str
    request_fingerprint: str
    browser_session_ref: str
    run_ref: str
    workspace_ref: str
    owner_ref: str
    allowed_action_classes: tuple[str, ...]
    origin_scope: str
    max_actions: int
    issued_at: datetime
    expires_at: datetime
    approval_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", _ref(self.lease_id, "lease_id"))
        object.__setattr__(
            self, "request_fingerprint", _ref(self.request_fingerprint, "request_fingerprint")
        )
        object.__setattr__(
            self, "browser_session_ref", _ref(self.browser_session_ref, "browser_session_ref")
        )
        object.__setattr__(self, "run_ref", _ref(self.run_ref, "run_ref"))
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "owner_ref", _ref(self.owner_ref, "owner_ref"))
        object.__setattr__(self, "approval_ref", _ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        # Slice 1: exactly one exact origin; the general #3607 policy allows up
        # to three exact origins without wildcards and is not exercised here.
        object.__setattr__(self, "origin_scope", _origin(self.origin_scope, "origin_scope"))
        actions = tuple(self.allowed_action_classes)
        if not actions:
            _refuse("lease must allow at least one bounded action class")
        if any(classify_browser_control_action(entry) != "lease_eligible" for entry in actions):
            _refuse("lease allowed_action_classes must be lease-eligible only")
        object.__setattr__(self, "allowed_action_classes", tuple(sorted(set(actions))))
        if (
            isinstance(self.max_actions, bool)
            or not isinstance(self.max_actions, int)
            or not 1 <= self.max_actions <= LEASE_MAX_ACTIONS_HARD_CAP
        ):
            _refuse(f"lease max_actions must be 1..{LEASE_MAX_ACTIONS_HARD_CAP}")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        lifetime = (expires - issued).total_seconds()
        if lifetime <= 0 or lifetime > LEASE_TTL_MAX_SECONDS:
            _refuse(f"lease lifetime must be positive and at most {LEASE_TTL_MAX_SECONDS} seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def allows(self, request: BrowserControlActionRequest) -> bool:
        return (
            request.action in self.allowed_action_classes
            and request.origin_ref == self.origin_scope
            and request.browser_session_ref == self.browser_session_ref
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
