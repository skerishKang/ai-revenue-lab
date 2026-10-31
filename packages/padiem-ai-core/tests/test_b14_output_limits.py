"""#3553 output-limit authority separation is retired.

The reference module and its exported authorities no longer exist; only the
provider-facing explicit max_tokens contract in b14_execution remains.
"""

from __future__ import annotations

import importlib.util

import padiem_ai_core
from padiem_ai_core.b14_execution import PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING


def test_b14_output_limits_module_and_attributes_no_longer_exist() -> None:
    assert importlib.util.find_spec("padiem_ai_core.b14_output_limits") is None
    for name in (
        "ModelOutputCapability",
        "OutputBudgetDecision",
        "OUTPUT_LIMIT_AUTHORITIES",
        "validate_output_budget",
    ):
        assert not hasattr(padiem_ai_core, name), name


def test_provider_explicit_output_ceiling_is_still_uncapped() -> None:
    assert PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING is None
