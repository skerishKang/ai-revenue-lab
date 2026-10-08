"""#3782: validate closed browser.control arguments BEFORE Core approval pause.

Core ToolRuntime checks USER_CONFIRMATION before tool input schema; without
this precheck an invalid request could produce a misleading approval prompt.
No site is accessed and no browser/input action is emitted here.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

_ALLOWED = frozenset({"scroll", "focus", "click", "type", "select"})
_FIELDS = frozenset({
    "browser_session_ref", "run_ref", "workspace_ref", "owner_ref",
    "device_id", "origin_scope", "allowed_action_classes", "ttl_seconds",
    "max_actions",
})
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_ORIGIN = re.compile(r"^https://[a-z0-9.-]+(?::[0-9]{1,5})?$")


def validate_browser_control_approval_arguments(arguments: Mapping[str, object]) -> None:
    """Reject unknown authority dimensions and noncanonical session scopes."""
    if not isinstance(arguments, Mapping) or set(arguments) != _FIELDS:
        raise ValueError("browser.control requires exact closed session arguments")
    for field in ("browser_session_ref", "run_ref", "workspace_ref", "owner_ref", "device_id"):
        value = arguments.get(field)
        if type(value) is not str or _REF.fullmatch(value) is None:
            raise ValueError("browser.control session identifier is invalid")
    origin = arguments.get("origin_scope")
    if (
        type(origin) is not str or len(origin) > 255
        or _ORIGIN.fullmatch(origin) is None
    ):
        raise ValueError("browser.control origin is invalid")
    try:
        url = urlsplit(origin)
        if not (
            url.scheme == "https"
            and url.hostname
            and url.port != 0
            and url.username is None
            and url.password is None
            and url.path in ("", "/")
            and not url.query
            and not url.fragment
            and not any(ch.isspace() for ch in origin)
            and origin == f"https://{url.netloc}{url.path}"
        ):
            raise ValueError("browser.control origin must be an HTTPS origin")
    except (ValueError, AttributeError) as exc:
        raise ValueError("browser.control origin must be an HTTPS origin") from exc
    actions = arguments.get("allowed_action_classes")
    if (
        type(actions) is not list or not 1 <= len(actions) <= 5
        or any(type(a) is not str or a not in _ALLOWED for a in actions)
        or actions != sorted(set(actions))
    ):
        raise ValueError("browser.control allowed actions must be sorted unique supported classes")
    ttl = arguments.get("ttl_seconds")
    budget = arguments.get("max_actions")
    if type(ttl) is not int or not 1 <= ttl <= 900:
        raise ValueError("browser.control TTL must be between 1 and 900")
    if type(budget) is not int or not 1 <= budget <= 100:
        raise ValueError("browser.control action budget must be between 1 and 100")
