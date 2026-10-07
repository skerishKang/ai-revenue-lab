"""B14 output-limit authorities (#3553).

Three different authorities govern how much output a B14 call may produce.
They must never be merged into a single number:

    PRODUCT_REQUESTED_LIMIT
        The output budget a product/feature actually requests. Today the
        explicit-request compatibility ceiling is the legacy B14 pilot
        validation value (4096, origin commit d8714ad4 / 2026-07-25);
        see padiem_ai_core.b14_execution.PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING.
        Widening it is a deliberate product decision, never an automatic
        copy of a provider maximum.

    RUNTIME_HARD_SAFETY_CEILING
        B14's resource-abuse guards, independent of max_tokens: response
        byte cap and request timeout bounds (b14_execution.MAX_B14_RESPONSE_BYTES,
        B14ExecutionConfig.timeout_seconds). Untouched by this contract.

    PROVIDER_MODEL_MAX_OUTPUT
        What the selected provider/model can technically produce. This is
        CAPABILITY METADATA ONLY — never the global request validator.

Capability semantics (fail-closed, no fabrication):

    - ``provider_model_max_output=None`` means UNKNOWN. Unknown capability is
      never turned into a number; the capability check is simply skipped and
      the product/runtime authorities stay in charge.
    - A capability record must carry its source and checked_at so its truth
      is auditable (e.g. provider official docs, gateway model list).

OMITTED_MAX_TOKENS_SEMANTICS_PRESERVED: omitted max_tokens is ``None``
(#3551) and stays outside this contract — this module only judges EXPLICIT
budgets.
"""

from __future__ import annotations

from dataclasses import dataclass

from .b14_execution import PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING

OUTPUT_LIMIT_AUTHORITIES = (
    "PRODUCT_REQUESTED_LIMIT",
    "RUNTIME_HARD_SAFETY_CEILING",
    "PROVIDER_MODEL_MAX_OUTPUT",
)


@dataclass(frozen=True, slots=True)
class ModelOutputCapability:
    """Capability metadata for one provider/model pair.

    ``provider_model_max_output`` is ``None`` when the true provider/model
    maximum is unknown. Unknown capability is NEVER fabricated into a number
    (UNKNOWN_PROVIDER_MAX_NOT_FABRICATED=YES).
    """

    provider_id: str
    model_id: str
    provider_model_max_output: int | None
    source: str
    checked_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id is required")
        max_output = self.provider_model_max_output
        if max_output is not None:
            if isinstance(max_output, bool) or not isinstance(max_output, int) or max_output <= 0:
                raise ValueError(
                    "provider_model_max_output must be a positive integer or None (unknown)"
                )
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("capability source is required")
        if not isinstance(self.checked_at, str) or not self.checked_at.strip():
            raise ValueError("capability checked_at is required")

    @property
    def capability_known(self) -> bool:
        return self.provider_model_max_output is not None


@dataclass(frozen=True, slots=True)
class OutputBudgetDecision:
    """Result of judging one explicit output budget against the authorities.

    ``ok`` is True when every supplied authority accepts the requested value.
    ``rejected_by`` names the first rejecting authority
    ("PRODUCT_REQUESTED_LIMIT" | "RUNTIME_HARD_SAFETY_CEILING" |
    "PROVIDER_MODEL_MAX_OUTPUT" | "PRODUCT_REQUESTED_LIMIT:format").
    """

    requested: int
    ok: bool
    rejected_by: str | None
    detail: str

    @property
    def authority(self) -> str | None:
        return self.rejected_by


def validate_output_budget(
    requested: object,
    *,
    product_max: int = PRODUCT_EXPLICIT_OUTPUT_TOKEN_CEILING,
    runtime_ceiling: int | None = None,
    capability: ModelOutputCapability | None = None,
) -> OutputBudgetDecision:
    """Judge one EXPLICIT output budget against the separated authorities.

    Semantics (conceptual contract for #3553):

        requested is a positive integer
        AND requested <= product_max                      (PRODUCT_REQUESTED_LIMIT)
        AND requested <= runtime_ceiling                  (RUNTIME_HARD_SAFETY_CEILING, when supplied)
        AND requested <= capability.provider_model_max_output
            (PROVIDER_MODEL_MAX_OUTPUT, only when reliable capability metadata
             is supplied; unknown capability is skipped, never fabricated)

    The default ``product_max`` is the legacy compatibility ceiling (4096).
    This function does NOT change B14ChatRequest validation; it makes the
    authorities explicit and testable for future deliberate widening.
    """

    def reject(authority: str, detail: str) -> OutputBudgetDecision:
        return OutputBudgetDecision(
            requested=requested if isinstance(requested, int) and not isinstance(requested, bool) else -1,
            ok=False,
            rejected_by=authority,
            detail=detail,
        )

    if isinstance(requested, bool) or not isinstance(requested, int):
        return reject(
            "PRODUCT_REQUESTED_LIMIT:format",
            "explicit max_tokens must be an integer (omitted stays None per #3551)",
        )
    if requested <= 0:
        return reject("PRODUCT_REQUESTED_LIMIT:format", "explicit max_tokens must be >= 1")
    if not isinstance(product_max, int) or isinstance(product_max, bool) or product_max <= 0:
        return reject("PRODUCT_REQUESTED_LIMIT:format", "product_max must be a positive integer")
    if requested > product_max:
        return reject(
            "PRODUCT_REQUESTED_LIMIT",
            f"requested {requested} exceeds the product explicit budget ceiling {product_max}",
        )
    if runtime_ceiling is not None:
        if isinstance(runtime_ceiling, bool) or not isinstance(runtime_ceiling, int) or runtime_ceiling <= 0:
            return reject("RUNTIME_HARD_SAFETY_CEILING:format", "runtime_ceiling must be a positive integer")
        if requested > runtime_ceiling:
            return reject(
                "RUNTIME_HARD_SAFETY_CEILING",
                f"requested {requested} exceeds the runtime hard safety ceiling {runtime_ceiling}",
            )
    if capability is not None and capability.provider_model_max_output is not None:
        if requested > capability.provider_model_max_output:
            return reject(
                "PROVIDER_MODEL_MAX_OUTPUT",
                (
                    f"requested {requested} exceeds the known provider/model capability "
                    f"{capability.provider_model_max_output} "
                    f"(source={capability.source}, checked_at={capability.checked_at})"
                ),
            )
    return OutputBudgetDecision(
        requested=requested,
        ok=True,
        rejected_by=None,
        detail="explicit output budget accepted by all supplied authorities",
    )
