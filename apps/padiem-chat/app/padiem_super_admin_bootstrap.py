"""PADIEM-wide host-only operator bootstrap for existing product admin gates.

Stage 1: resolve ONE trusted Worker binding for B66 + Central Model Admin.
This function grants no role by itself. Both existing D1 authorizers must
independently verify the canonical Google provider subject and derived user_id.
No browser-supplied email, Max tier, session claim or product membership is input.

If the shared binding is present but invalid, or disagrees with either
nonempty legacy product binding, BOTH outputs fail closed. When absent,
legacy product bootstrap remains unchanged for rollout compatibility.
Claw/Chat general-admin and global member entitlement are NOT wired here.
"""
from __future__ import annotations

import re

_TRUSTED_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+\Z"
)


def _normalize_trusted_email(value: object) -> str:
    if not isinstance(value, str):
        return ""
    email = value.strip().lower()
    if not email or len(email) > 254 or _TRUSTED_EMAIL.fullmatch(email) is None:
        return ""
    return email


def resolve_super_admin_bootstrap(
    *, shared: object, legacy_b66: object, legacy_central: object,
) -> tuple[str, str]:
    """Return B66 and Central operator email settings, never a permission grant.

    Missing shared binding (None) preserves existing independent configuration.
    An explicitly present but invalid shared binding cannot downgrade to
    legacy roles, as that could hide a broken global security configuration.
    """
    b66 = _normalize_trusted_email(legacy_b66)
    central = _normalize_trusted_email(legacy_central)
    if shared is None:
        return b66, central

    operator = _normalize_trusted_email(shared)
    if not operator:
        return "", ""

    for raw in (legacy_b66, legacy_central):
        if raw is not None and (not isinstance(raw, str) or raw.strip()):
            if _normalize_trusted_email(raw) != operator:
                return "", ""
    return operator, operator
