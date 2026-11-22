"""Parsed facts for the #3406 canonical B66 CompanyProfile static contracts.

Raw shipped-source reads live here (reusing claw_static); the test receives
named facts — missing-token lists and booleans — instead of raw source text.
Runtime/API contracts stay in the test itself.
"""
from __future__ import annotations

from _support.claw_static import migration_source, server_source, sheet


def default_day_literals() -> list[str]:
    source = server_source("b66_company_profile")
    return [
        token for token in ('"defaultValidityDays": 7', '"defaultValidityDays": 30')
        if token in source
    ]


def migration_facts() -> dict:
    sql = migration_source("023_b66_company_profile.sql")
    upper = sql.upper()
    return {
        "missing_statements": [
            statement for statement in (
                "CREATE TABLE IF NOT EXISTS b66_company_profile",
                "PRIMARY KEY (user_id, workspace_id)",
                "REFERENCES users(id) ON DELETE CASCADE",
                "default_validity_days INTEGER",
                "default_tax_mode TEXT",
            ) if statement not in sql
        ],
        "forbidden_statements": [
            statement for statement in ("DEFAULT 7", "DEFAULT 30", "DROP TABLE", "ALTER TABLE")
            if statement in upper
        ],
    }


def runtime_overlay_facts() -> dict:
    source = sheet("b66-quote-runtime.js")
    return {
        "missing_rules": [
            token for token in (
                "companyProfileForRender",
                "interpreted.data.company_profile",
                "!Number.isInteger(profile.defaultValidityDays)",
                "companyProfile: profileResult.profile",
            ) if token not in source
        ],
        "forbidden_tokens": [
            token for token in (
                "skill: effectiveSkill", "copy.fixedDefaults.sender",
                "copy.fixedDefaults.validDays", "localStorage",
            ) if token in source
        ],
    }
