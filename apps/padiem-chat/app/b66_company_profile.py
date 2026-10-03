"""Canonical B66 account/workspace company profile (#3406).

Profiles are partial by design: assisted-alpha onboarding stores only facts
actually reviewed with the customer or present in approved source material.
Missing facts stay missing until the user/operator supplies them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

MAX_USER_ID_CHARS = 160
MAX_WORKSPACE_ID_CHARS = 200
MAX_TEXT = 500
MAX_EMAIL = 320
TAX_MODES = frozenset({"EXCLUSIVE", "INCLUSIVE", "EXEMPT"})
PROFILE_KEYS = frozenset({
    "company", "representative", "contactPerson", "businessNumber",
    "address", "phone", "email", "defaultValidityDays", "defaultTaxMode",
})


class CompanyProfileError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def _owner(value: Any, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise CompanyProfileError(f"{label} is required")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        raise CompanyProfileError(f"{label} is invalid")
    return cleaned


def _optional_text(value: Any, *, label: str, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CompanyProfileError(f"{label} is invalid")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise CompanyProfileError(f"{label} is too long")
    return cleaned


def canonicalize_company_profile(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CompanyProfileError("company profile must be an object")
    unknown = set(raw) - PROFILE_KEYS
    if unknown:
        raise CompanyProfileError("unsupported company profile field")
    profile: dict[str, Any] = {
        "company": _optional_text(raw.get("company"), label="company"),
        "representative": _optional_text(raw.get("representative"), label="representative"),
        "contactPerson": _optional_text(raw.get("contactPerson"), label="contactPerson"),
        "businessNumber": _optional_text(raw.get("businessNumber"), label="businessNumber", limit=80),
        "address": _optional_text(raw.get("address"), label="address"),
        "phone": _optional_text(raw.get("phone"), label="phone", limit=100),
        "email": _optional_text(raw.get("email"), label="email", limit=MAX_EMAIL),
        "defaultValidityDays": None,
        "defaultTaxMode": None,
    }

    validity = raw.get("defaultValidityDays")
    if validity not in (None, ""):
        if isinstance(validity, bool):
            raise CompanyProfileError("defaultValidityDays is invalid")
        try:
            validity_int = int(validity)
        except (TypeError, ValueError) as exc:
            raise CompanyProfileError("defaultValidityDays is invalid") from exc
        if validity_int < 0 or validity_int > 3650:
            raise CompanyProfileError("defaultValidityDays is invalid")
        profile["defaultValidityDays"] = validity_int

    tax_mode = raw.get("defaultTaxMode")
    if tax_mode not in (None, ""):
        if not isinstance(tax_mode, str) or tax_mode.strip() not in TAX_MODES:
            raise CompanyProfileError("defaultTaxMode is invalid")
        profile["defaultTaxMode"] = tax_mode.strip()
    if not any(value is not None for value in profile.values()):
        raise CompanyProfileError("company profile cannot be empty")
    return profile


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return None


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "company": row.get("company"),
        "representative": row.get("representative"),
        "contactPerson": row.get("contact_person"),
        "businessNumber": row.get("business_number"),
        "address": row.get("address"),
        "phone": row.get("phone"),
        "email": row.get("email"),
        "defaultValidityDays": row.get("default_validity_days"),
        "defaultTaxMode": row.get("default_tax_mode"),
        "updatedAt": row.get("updated_at"),
    }


class CompanyProfileStore(Protocol):
    async def get_profile(self, *, user_id: str, workspace_id: str) -> dict[str, Any] | None: ...
    async def put_profile(
        self, *, user_id: str, workspace_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]: ...


class D1CompanyProfileStore:
    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def get_profile(
        self, *, user_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        owner = _owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row = await self._first(
            "SELECT company, representative, contact_person, business_number, "
            "address, phone, email, default_validity_days, default_tax_mode, updated_at "
            "FROM b66_company_profile WHERE user_id=? AND workspace_id=?",
            owner,
            workspace,
        )
        return _public(row) if row else None

    async def put_profile(
        self, *, user_id: str, workspace_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        owner = _owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        canonical = canonicalize_company_profile(profile)
        now = _now_iso()
        existing = await self._first(
            "SELECT user_id FROM b66_company_profile WHERE user_id=? AND workspace_id=?",
            owner,
            workspace,
        )
        values = (
            canonical["company"],
            canonical["representative"],
            canonical["contactPerson"],
            canonical["businessNumber"],
            canonical["address"],
            canonical["phone"],
            canonical["email"],
            canonical["defaultValidityDays"],
            canonical["defaultTaxMode"],
        )
        if existing:
            await self._run(
                "UPDATE b66_company_profile SET company=?, representative=?, contact_person=?, "
                "business_number=?, address=?, phone=?, email=?, default_validity_days=?, "
                "default_tax_mode=?, updated_at=? WHERE user_id=? AND workspace_id=?",
                *values,
                now,
                owner,
                workspace,
            )
        else:
            await self._run(
                "INSERT INTO b66_company_profile "
                "(user_id, workspace_id, company, representative, contact_person, business_number, "
                "address, phone, email, default_validity_days, default_tax_mode, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                owner,
                workspace,
                *values,
                now,
                now,
            )

        stored = await self.get_profile(user_id=owner, workspace_id=workspace)
        if stored is None:
            raise CompanyProfileError("company profile write failed")
        return stored


__all__ = [
    "CompanyProfileError",
    "CompanyProfileStore",
    "D1CompanyProfileStore",
    "PROFILE_KEYS",
    "canonicalize_company_profile",
]
