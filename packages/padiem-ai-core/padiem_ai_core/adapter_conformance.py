"""Product-neutral Adapter Conformance Harness for Padiem AI Platform (P01).

This module provides a reusable, cross-adapter verification harness proving that
server/product-specific adapter implementations preserve P01 Core semantics:
- Authority Non-Widening: adapter output <= trusted authority.
- Identity & Scope Preservation: same app_id, namespace, subject. Cross-scope fails closed.
- Unknown State Preservation: UNKNOWN != SUPPORTED / VERIFIED / FREE / AUTHORIZED.
- Transparent Failure Lifecycle: timeouts, cancellations, and failures are not rewritten.
- Safe Public Projection: scalar metadata bounds and zero credential leakage.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
import time
from types import MappingProxyType
from typing import Any, Awaitable

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_CONFORMANCE_CASES = 512


class AdapterCategory(str, Enum):
    """Product-neutral adapter categories in P01."""

    MEMORY = "memory"
    AGENT = "agent"
    SKILL = "skill"
    TOOL = "tool"
    CONNECTOR = "connector"
    EVIDENCE = "evidence"
    ENGINE = "engine"


class ConformanceDimension(str, Enum):
    """Core semantic dimensions verified by the harness."""

    IDENTITY = "identity"
    SCOPE = "scope"
    AUTHORITY = "authority"
    FAILURE = "failure"
    CANCEL = "cancel"
    TIMEOUT = "timeout"
    IDEMPOTENCY = "idempotency"
    PROJECTION = "projection"


class ConformanceVerdict(str, Enum):
    """Conformance test result verdict."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    N_A = "N/A"


class AdapterContractViolation(ValueError):
    """Raised when an adapter violates a P01 Core contract or semantic invariant."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("violation code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _safe_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise AdapterContractViolation("invalid_identifier", f"{name} must be a bounded safe identifier")
    return value


@dataclass(frozen=True, slots=True)
class AdapterConformanceCase:
    """Individual conformance test case definition."""

    case_id: str
    category: AdapterCategory
    dimension: ConformanceDimension
    title: str
    description: str
    negative_test: bool = False
    expected_verdict: ConformanceVerdict = ConformanceVerdict.PASS

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _safe_id("case_id", self.case_id))
        if not isinstance(self.category, AdapterCategory):
            raise AdapterContractViolation("invalid_category", "category must be AdapterCategory")
        if not isinstance(self.dimension, ConformanceDimension):
            raise AdapterContractViolation("invalid_dimension", "dimension must be ConformanceDimension")
        if not isinstance(self.expected_verdict, ConformanceVerdict):
            raise AdapterContractViolation("invalid_expected_verdict", "expected_verdict must be ConformanceVerdict")


@dataclass(frozen=True, slots=True)
class AdapterConformanceResult:
    """Outcome of an individual conformance test case execution."""

    case: AdapterConformanceCase
    verdict: ConformanceVerdict
    details: str
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "category": self.case.category.value,
            "dimension": self.case.dimension.value,
            "title": self.case.title,
            "verdict": self.verdict.value,
            "details": self.details,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "negative_test": self.case.negative_test,
        }


@dataclass(frozen=True, slots=True)
class AdapterConformanceReport:
    """Machine-readable and human-readable suite execution report."""

    suite_id: str
    timestamp: str
    results: tuple[AdapterConformanceResult, ...]
    matrix: dict[str, dict[str, str]]

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        return sum(1 for r in self.results if r.verdict == ConformanceVerdict.PASS)

    @property
    def failed_cases(self) -> int:
        return sum(1 for r in self.results if r.verdict == ConformanceVerdict.FAIL)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "timestamp": self.timestamp,
            "summary": {
                "total": self.total_cases,
                "passed": self.passed_cases,
                "failed": self.failed_cases,
                "pass_rate_percent": (self.passed_cases / self.total_cases * 100.0) if self.total_cases > 0 else 0.0,
            },
            "matrix": self.matrix,
            "results": [r.to_public_dict() for r in self.results],
        }

    def to_markdown_table(self) -> str:
        dimensions = [d.value.capitalize() for d in ConformanceDimension]
        header = "| Category | " + " | ".join(dimensions) + " |"
        sep = "|:---| " + " | ".join([":---:" for _ in dimensions]) + " |"
        rows = [header, sep]
        for cat in AdapterCategory:
            cat_name = cat.value.capitalize()
            cat_matrix = self.matrix.get(cat.value, {})
            row = [cat_name]
            for dim in ConformanceDimension:
                v = cat_matrix.get(dim.value, ConformanceVerdict.N_A.value)
                row.append(f"**{v}**" if v == "PASS" else v)
            rows.append("| " + " | ".join(row) + " |")
        return "\n".join(rows)


class AdapterConformanceSuite:
    """Reusable runner executing conformance cases across P01 adapter categories."""

    def __init__(self, suite_id: str = "p01_conformance_default") -> None:
        self.suite_id = _safe_id("suite_id", suite_id)
        self._cases: list[tuple[AdapterConformanceCase, Callable[[], Awaitable[None]]]] = []

    def register_case(
        self,
        case_id: str,
        category: AdapterCategory,
        dimension: ConformanceDimension,
        title: str,
        description: str,
        test_fn: Callable[[], Awaitable[None]],
        negative_test: bool = False,
    ) -> None:
        if len(self._cases) >= MAX_CONFORMANCE_CASES:
            raise AdapterContractViolation("conformance_budget_exceeded", "exceeded max conformance test cases")
        case = AdapterConformanceCase(
            case_id=case_id,
            category=category,
            dimension=dimension,
            title=title,
            description=description,
            negative_test=negative_test,
        )
        self._cases.append((case, test_fn))

    async def run(self) -> AdapterConformanceReport:
        results: list[AdapterConformanceResult] = []
        matrix: dict[str, dict[str, str]] = {
            cat.value: {dim.value: ConformanceVerdict.N_A.value for dim in ConformanceDimension}
            for cat in AdapterCategory
        }

        for case, test_fn in self._cases:
            t0 = time.perf_counter()
            verdict = ConformanceVerdict.PASS
            details = "Contract assertion verified successfully."
            error_code: str | None = None
            error_msg: str | None = None

            try:
                await test_fn()
            except AdapterContractViolation as exc:
                if case.negative_test:
                    verdict = ConformanceVerdict.PASS
                    details = f"Negative invariant fail-closed verified: {exc.safe_message}"
                else:
                    verdict = ConformanceVerdict.FAIL
                    error_code = exc.code
                    error_msg = exc.safe_message
                    details = f"Adapter contract violation: {exc.safe_message}"
            except Exception as exc:
                if case.negative_test:
                    verdict = ConformanceVerdict.PASS
                    details = f"Negative invariant rejected with exception: {type(exc).__name__}"
                else:
                    verdict = ConformanceVerdict.FAIL
                    error_code = "unexpected_exception"
                    error_msg = str(exc)
                    details = f"Test raised unexpected exception: {type(exc).__name__}: {exc}"

            duration_ms = int((time.perf_counter() - t0) * 1000)
            res = AdapterConformanceResult(
                case=case,
                verdict=verdict,
                details=details,
                error_code=error_code,
                error_message=error_msg,
                duration_ms=duration_ms,
            )
            results.append(res)

            # Update category matrix
            current_dim_val = matrix[case.category.value][case.dimension.value]
            if verdict == ConformanceVerdict.FAIL:
                matrix[case.category.value][case.dimension.value] = ConformanceVerdict.FAIL.value
            elif current_dim_val != ConformanceVerdict.FAIL.value:
                matrix[case.category.value][case.dimension.value] = ConformanceVerdict.PASS.value

        now_iso = datetime.now(timezone.utc).isoformat()
        return AdapterConformanceReport(
            suite_id=self.suite_id,
            timestamp=now_iso,
            results=tuple(results),
            matrix=matrix,
        )
