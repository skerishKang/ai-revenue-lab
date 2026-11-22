"""Parsed facts for the #3237 Web Claw Automation read-only UI contracts.

Raw shipped-source reads live here (reusing claw_static and html_tags); the
test asserts on named facts. The Node harness behavior stays in the test.
"""
from __future__ import annotations

import locale_bundle
from _support.claw_static import sheet
from _support.html_tags import tags_for_page

_MARKUP = (
    "automationNavButton", "nav-automation", "clawAutomation", "clawAutomationList",
    "clawAutomationLoading", "clawAutomationError", "clawAutomationEmpty",
    "clawAutomationRetry", "automationViewSignedOut", "claw-automation-signed-out",
    "clawAutomationTitle", "aria-live",
)

_KEYS = (
    "nav-automation", "claw-automation-title", "claw-automation-help",
    "claw-automation-loading", "claw-automation-error", "claw-automation-empty",
    "claw-automation-scheduler-note", "automation-rule-setting", "automation-rule-on",
    "automation-rule-off", "automation-rule-quarantined",
)


def _index() -> str:
    return sheet("index.html")


def _locale() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def _missing(value: str, needles) -> list[str]:
    return [needle for needle in needles if needle not in value]


def markup_facts() -> dict:
    html = _index()
    ids = {attrs["id"] for _tag, attrs in tags_for_page("index.html") if attrs.get("id")}
    return {
        "missing_markup": _missing(html, (
            'id="automationNavButton"', 'data-locale-key="nav-automation"',
            'id="clawAutomation"', 'id="clawAutomationList"',
            'id="clawAutomationLoading"', 'id="clawAutomationError"',
            'id="clawAutomationEmpty"', 'id="clawAutomationRetry"',
            'id="automationViewSignedOut"', 'data-locale-key="claw-automation-signed-out"',
            'aria-labelledby="clawAutomationTitle"',
            'id="clawAutomationTitle"', 'aria-live="polite"',
        )),
        "ids": ids,
    }


def scheduler_locale_facts() -> dict:
    html = _index()
    locale = _locale()
    return {
        "missing_markup": _missing(html, (
            'id="clawAutomationSchedulerNote"',
            'data-locale-key="claw-automation-scheduler-note"',
            'id="clawAutomationLoading"',
        )),
        "key_counts": {
            key: locale.count(f'"{key}"')
            for key in ("claw-automation-scheduler-note", "claw-automation-signed-out",
                        "automation-rule-setting", "automation-rule-quarantined")
        },
        "bare_keys_present": [
            key for key in ("automation-rule-enabled", "automation-rule-disabled")
            if f'"{key}"' in locale
        ],
    }


def mutation_module_facts() -> dict:
    source = sheet("chat-automation-module.js")
    return {
        "forbidden_tokens": _present(source, (
            "createRule", "updateRule", "deleteRule", "runNow",
            "set_rule_enabled", "PUT", "DELETE",
        )),
    }


def _present(value: str, needles) -> list[str]:
    return [needle for needle in needles if needle in value]


def skill_surface_facts() -> dict:
    app = sheet("app.js")
    html = _index()
    return {
        "forbidden_tokens": _present(app, ("/api/claw/skills", "claw_skill_routes", "business-66")),
        "forbidden_markup": _present(html, ("quote-skill",)),
    }


def locale_key_facts() -> dict:
    locale = _locale()
    return {
        "missing_keys": _missing(locale, tuple(f'"{key}"' for key in _KEYS)),
        "nav_automation_count": locale.count('"nav-automation"'),
    }


def inner_html_facts() -> dict:
    names = ("app.js", "chat-automation-module.js", "chat-automation-form-module.js",
             "chat-local-pc-panel-module.js")
    return [
        {"file": name, "sinks": _present(sheet(name), ("innerHTML", "insertAdjacentHTML"))}
        for name in names
    ]
