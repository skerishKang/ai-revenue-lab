"""#2812: Claw deterministic supplier quote comparison + draft-only negotiation.

Product-flow boundary that wires the already-implemented Claw Ops comparison
authority (``ops_comparison.SupplierComparisonEngine``) and the existing
``ops_contracts`` business objects into the Claw manual-intake path, so a
connectorless paste of supplier quotes produces a real comparison and a
negotiation draft instead of staying isolated in the domain/test layer.

Every figure in the result comes from a captured quote field. The engine ranks
by price, then by promised delivery date, then by payment terms, and the
negotiation target comes from ``negotiation_target_from_competing_quote``, which
is bounded by another captured quote. Nothing is asked of a model, and a value
the caller did not supply stays visible as an engine ``unknown_fields`` entry
rather than being filled in:

- no P01/Engine/B14 import, dispatch or credential in this module;
- no outbound port, so a negotiation can never leave the product;
- lead times are not converted into delivery dates (``SupplierQuote`` models a
  promised date only), so a lead-time string is rejected rather than inferred;
- ``rfq_id`` is a required field of the existing ``SupplierQuote`` contract. A
  manual paste has no RFQ, so it carries a self-describing
  ``rfq_manual_<supplier_id>`` placeholder that no workflow lookup resolves.

#1408's ``QuoteComparison`` record requires a bound ``commercial_request_id``,
which a connectorless paste does not have, so the projected output is the
engine's own ``SupplierComparisonAnalysis`` instead of a fabricated linkage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, NoReturn, Sequence

from .contracts import ContractError
from .ops_comparison import (
    ComparisonMode,
    ComparisonWeights,
    NegotiationTarget,
    SupplierComparisonAnalysis,
    SupplierComparisonEngine,
    SupplierDecisionScore,
)
from .ops_contracts import (
    ArtifactRef,
    Money,
    NegotiationDraft,
    PaymentTerms,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
)
from .security import redact_secrets

DETERMINISTIC_COMPARE = True
LLM_PRICE_INVENTION = False
NEGOTIATION_DRAFT_ONLY = True
EXTERNAL_SEND_SUPPORTED = False
PROVIDER_CALL_REQUIRED = False
MODEL_CALLS = 0
EXTERNAL_SENDS = 0

MAX_SUPPLIERS = 100
MAX_AMOUNT_MINOR = 10**15
DEFAULT_WORKSPACE_ID = "claw_manual_intake"
MANUAL_RFQ_PREFIX = "rfq_manual_"
EVIDENCE_KIND = "claw_manual_quote_evidence"
SUPPLIER_LABEL_MAX_CHARS = 200
ITEM_LABEL_MAX_CHARS = 300
EVIDENCE_REF_MAX_CHARS = 256
PAYMENT_TERMS_LABEL_MAX_CHARS = 300
NEGOTIATION_MESSAGE_MAX_CHARS = 4000
COMPARISON_DOCUMENT_TYPE = "quote_comparison"
UNKNOWN_LABEL = "미확인"

_VALID_MODES = tuple(mode.value for mode in ComparisonMode)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_INT_RE = re.compile(r"-?[0-9]{1,16}")

NEGOTIATION_REASON_SINGLE_SUPPLIER = "single_supplier_no_competing_quote"
NEGOTIATION_REASON_NO_COMPETING_QUOTE = "no_same_currency_competing_quote"

QUOTE_COMPARE_ERROR_CODES = frozenset(
    {
        "invalid_payload",
        "payload_too_large",
        "invalid_workspace_id",
        "suppliers_required",
        "too_many_suppliers",
        "invalid_supplier_entry",
        "invalid_supplier_id",
        "invalid_supplier_label",
        "invalid_item_label",
        "invalid_currency",
        "mixed_currency",
        "supplier_price_missing",
        "invalid_price",
        "supplier_total_must_be_positive",
        "invalid_quantity",
        "supplier_unit_price_underivable",
        "supplier_line_total_mismatch",
        "fractional_line_total",
        "invalid_delivery_date",
        "invalid_payment_terms",
        "invalid_evidence_reference",
        "invalid_comparison_mode",
        "invalid_comparison_weights",
        "comparison_unavailable",
    }
)


class OpsQuoteCompareFlowError(ContractError):
    """Fail-closed flow error carrying one code from the closed vocabulary."""

    def __init__(self, error_code: str, message: str) -> None:
        if error_code not in QUOTE_COMPARE_ERROR_CODES:
            raise ValueError(f"undeclared quote compare error code: {error_code}")
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.public_message = message


def _fail(error_code: str, message: str) -> NoReturn:
    raise OpsQuoteCompareFlowError(error_code, message)


def _mapping(value: Any, code: str, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code, f"{field_name} must be a JSON object")
    return value


def _text(
    value: Any,
    code: str,
    field_name: str,
    *,
    limit: int,
    required: bool = True,
) -> str | None:
    if value is None:
        if required:
            _fail(code, f"{field_name} is required")
        return None
    if not isinstance(value, str):
        _fail(code, f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        if required:
            _fail(code, f"{field_name} is required")
        return None
    if len(normalized) > limit:
        _fail(code, f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(normalized):
        _fail(code, f"{field_name} contains control characters")
    return normalized


def _minor_amount(value: Any, field_name: str) -> int | None:
    """Integer minor units only: binary floats are never accepted as money."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        _fail("invalid_price", f"{field_name} must be an integer minor amount, not a float")
    if isinstance(value, str):
        text = value.strip()
        if not _INT_RE.fullmatch(text):
            _fail("invalid_price", f"{field_name} must be an integer minor amount")
        value = int(text)
    elif not isinstance(value, int):
        _fail("invalid_price", f"{field_name} must be an integer minor amount")
    if abs(value) > MAX_AMOUNT_MINOR:
        _fail("invalid_price", f"{field_name} exceeds the supported amount bound")
    return value


def _quantity(value: Any) -> Decimal | int:
    """Hand the captured quantity to the existing contract validator."""
    if value is None:
        return 1
    if isinstance(value, bool) or isinstance(value, float):
        _fail("invalid_quantity", "quantity must not use binary float")
    if isinstance(value, int):
        return value
    text = _text(value, "invalid_quantity", "quantity", limit=40)
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        _fail("invalid_quantity", "quantity must be decimal-compatible")


def _iso_date(value: Any, field_name: str) -> date | None:
    text = _text(value, "invalid_delivery_date", field_name, limit=32, required=False)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        _fail(
            "invalid_delivery_date",
            f"{field_name} must be an ISO YYYY-MM-DD date; lead times are not converted into dates",
        )


def _line_for(entry: Mapping[str, Any], *, supplier_id: str) -> SupplierQuoteLine:
    unit_minor = _minor_amount(entry.get("unit_price_minor"), "unit_price_minor")
    total_minor = _minor_amount(entry.get("total_minor"), "total_minor")
    if unit_minor is None and total_minor is None:
        _fail("supplier_price_missing", "a captured unit price or total is required to compare")
    quantity = _quantity(entry.get("quantity"))

    if unit_minor is None:
        # Only a total was captured: derive the unit price exactly, or fail
        # closed rather than rounding a price into existence.
        assert total_minor is not None
        if quantity == 1:
            unit_minor = total_minor
        else:
            derived = Decimal(total_minor) / Decimal(quantity)
            if not derived.is_finite() or derived != derived.to_integral_value():
                _fail(
                    "supplier_unit_price_underivable",
                    "total is not divisible by quantity; capture the unit price instead",
                )
            unit_minor = int(derived)
    else:
        expected = Decimal(unit_minor) * Decimal(quantity)
        if total_minor is not None and expected != Decimal(total_minor):
            _fail(
                "supplier_line_total_mismatch", "captured total does not equal quantity times unit price"
            )
        if not expected.is_finite() or abs(expected) > MAX_AMOUNT_MINOR:
            _fail("invalid_price", "quantity times unit price exceeds the supported amount bound")

    currency = (
        _text(entry.get("currency"), "invalid_currency", "currency", limit=3, required=False) or "KRW"
    ).upper()
    try:
        line = SupplierQuoteLine(
            line_id=f"{supplier_id}.line1",
            quantity=quantity,
            unit_price=Money(unit_minor, currency),
        )
        captured_total = line.total
    except ContractError as exc:
        if "fractional" in str(exc):
            _fail("fractional_line_total", str(exc))
        _fail("invalid_supplier_entry", str(exc))
    if captured_total.amount_minor <= 0:
        _fail("supplier_total_must_be_positive", "captured quote total must be positive")
    return line


def _payment_terms(value: Any, supplier_id: str) -> PaymentTerms | None:
    if value is None:
        return None
    terms = _mapping(value, "invalid_payment_terms", "payment_terms")
    label = _text(
        terms.get("label"),
        "invalid_payment_terms",
        "payment_terms.label",
        limit=PAYMENT_TERMS_LABEL_MAX_CHARS,
        required=False,
    )
    due_days = terms.get("due_days")
    if due_days is not None and (isinstance(due_days, bool) or not isinstance(due_days, int)):
        _fail("invalid_payment_terms", "payment_terms.due_days must be an integer number of days")
    prepaid = terms.get("prepaid", False)
    if not isinstance(prepaid, bool):
        _fail("invalid_payment_terms", "payment_terms.prepaid must be a boolean")
    if label is None and due_days is None and not prepaid:
        return None
    try:
        return PaymentTerms(
            terms_id=f"terms_{supplier_id}",
            label=label or UNKNOWN_LABEL,
            due_days=due_days,
            prepaid=prepaid,
        )
    except ContractError as exc:
        _fail("invalid_payment_terms", str(exc))


def _evidence_ref(entry: Mapping[str, Any], supplier_id: str) -> ArtifactRef | None:
    reference = _text(
        entry.get("evidence_ref"),
        "invalid_evidence_reference",
        "evidence_ref",
        limit=EVIDENCE_REF_MAX_CHARS,
        required=False,
    )
    digest = _text(
        entry.get("evidence_sha256"),
        "invalid_evidence_reference",
        "evidence_sha256",
        limit=64,
        required=False,
    )
    if reference is None and digest is None:
        return None
    normalized_digest = digest.lower() if digest else None
    if normalized_digest is not None and not _SHA256_RE.fullmatch(normalized_digest):
        _fail("invalid_evidence_reference", "evidence_sha256 must be a SHA-256 hex digest")
    try:
        return ArtifactRef(
            artifact_id=f"evidence_{supplier_id}",
            kind=EVIDENCE_KIND,
            display_name=reference or "",
            content_sha256=normalized_digest,
        )
    except ContractError as exc:
        _fail("invalid_evidence_reference", str(exc))


def _quote_from_entry(
    raw_entry: Any,
    *,
    workspace_id: str,
    received_at: datetime,
) -> tuple[SupplierQuote, str, str]:
    entry = _mapping(raw_entry, "invalid_supplier_entry", "supplier entry")
    supplier_id = _text(entry.get("supplier_id"), "invalid_supplier_id", "supplier_id", limit=128)
    assert supplier_id is not None
    line = _line_for(entry, supplier_id=supplier_id)
    delivery = _iso_date(entry.get("promised_delivery_date"), "promised_delivery_date")
    terms = _payment_terms(entry.get("payment_terms"), supplier_id)
    evidence = _evidence_ref(entry, supplier_id)
    quote_id = _text(
        entry.get("quote_id"), "invalid_supplier_id", "quote_id", limit=128, required=False
    )
    version = entry.get("quote_version")
    if version is None:
        version = 1
    if isinstance(version, bool) or not isinstance(version, int):
        _fail("invalid_supplier_entry", "quote_version must be an integer")
    try:
        quote = SupplierQuote(
            quote_id=quote_id or f"quote_{supplier_id}",
            workspace_id=workspace_id,
            rfq_id=f"{MANUAL_RFQ_PREFIX}{supplier_id}",
            supplier_id=supplier_id,
            version=version,
            lines=(line,),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=received_at,
            promised_delivery_date=delivery,
            payment_terms=terms,
            source_artifact=evidence,
        )
    except ContractError as exc:
        _fail("invalid_supplier_entry", str(exc))
    label = _text(
        entry.get("supplier_label"),
        "invalid_supplier_label",
        "supplier_label",
        limit=SUPPLIER_LABEL_MAX_CHARS,
        required=False,
    )
    item = _text(
        entry.get("item_label"),
        "invalid_item_label",
        "item_label",
        limit=ITEM_LABEL_MAX_CHARS,
        required=False,
    )
    return quote, label or supplier_id, item or ""


@dataclass(frozen=True, slots=True)
class SupplierQuoteComparisonOutcome:
    """Deterministic comparison plus a draft-only negotiation projection."""

    workspace_id: str
    mode: ComparisonMode
    weights: ComparisonWeights
    currency: str
    analysis: SupplierComparisonAnalysis
    quotes: tuple[SupplierQuote, ...]
    supplier_labels: Mapping[str, str]
    item_labels: Mapping[str, str]
    negotiation: NegotiationDraft | None
    negotiation_target: NegotiationTarget | None
    negotiation_unavailable_reason: str | None

    def quote_for(self, supplier_id: str) -> SupplierQuote:
        for quote in self.quotes:
            if quote.supplier_id == supplier_id:
                return quote
        raise AssertionError("every score must reference a captured quote")

    def score_for(self, supplier_id: str) -> SupplierDecisionScore:
        for item in self.analysis.scores:
            if item.supplier_id == supplier_id:
                return item
        raise AssertionError("every supplier must have a score")

    @property
    def recommended_supplier_id(self) -> str:
        return self.analysis.recommended_supplier_id

    def label(self, supplier_id: str) -> str:
        return self.supplier_labels.get(supplier_id, supplier_id)

    def first_in_rank(self, rank: str) -> SupplierDecisionScore | None:
        for item in self.analysis.scores:
            if getattr(item, rank) == 1:
                return item
        return None

    def document_table(self) -> tuple[tuple[str, str, str, str], ...]:
        """Rows for the shared 품명/수량/단가/금액 business table, in engine order."""
        rows: list[tuple[str, str, str, str]] = []
        for item in self.analysis.scores:
            quote = self.quote_for(item.supplier_id)
            line = quote.lines[0]
            rows.append(
                (
                    self.label(item.supplier_id),
                    format(line.quantity, "f"),
                    _display_amount(line.unit_price),
                    _display_amount(item.total),
                )
            )
        return tuple(rows)

    def document_total(self) -> str:
        winner = self.score_for(self.recommended_supplier_id)
        return _display_amount(winner.total)

    def document_title(self) -> str:
        return (
            f"공급업체 견적 비교 초안 ({self.mode.value}) — {len(self.analysis.scores)}개 공급업체"
        )

    def _negotiation_dict(self) -> dict[str, Any] | None:
        draft = self.negotiation
        target = self.negotiation_target
        if draft is None or target is None:
            return None
        return {
            "negotiation_id": draft.negotiation_id,
            "supplier_id": draft.supplier_id,
            "supplier_label": redact_secrets(self.label(draft.supplier_id)),
            "quote_id": draft.quote_id,
            "quote_version": draft.quote_version,
            "version": draft.version,
            "current_total": target.current_total.safe_dict(),
            "target_total": target.target_total.safe_dict(),
            "basis": target.basis,
            "message": redact_secrets(draft.message),
            "status": "draft_only",
            "send_performed": False,
        }

    def safe_dict(self) -> dict[str, Any]:
        suppliers: list[dict[str, Any]] = []
        for item in self.analysis.scores:
            quote = self.quote_for(item.supplier_id)
            terms = quote.payment_terms
            evidence = quote.source_artifact.display_name if quote.source_artifact else ""
            suppliers.append(
                {
                    "supplier_id": item.supplier_id,
                    "supplier_label": redact_secrets(self.label(item.supplier_id)),
                    "item_label": redact_secrets(self.item_labels.get(item.supplier_id, "")),
                    "quote_id": item.quote_id,
                    "quote_version": item.quote_version,
                    "total": item.total.safe_dict(),
                    "promised_delivery_date": (
                        item.promised_delivery_date.isoformat() if item.promised_delivery_date else None
                    ),
                    "payment_terms_label": redact_secrets(terms.label if terms else ""),
                    "due_days": item.due_days,
                    "prepaid": item.prepaid,
                    "price_rank": item.price_rank,
                    "delivery_rank": item.delivery_rank,
                    "cashflow_rank": item.cashflow_rank,
                    "score_basis_points": item.score_basis_points,
                    "unknown_fields": list(item.unknown_fields),
                    "evidence_ref": redact_secrets(evidence),
                }
            )
        return {
            "workspace_id": self.workspace_id,
            "mode": self.mode.value,
            "weights": {
                "price": self.weights.price,
                "delivery": self.weights.delivery,
                "cashflow": self.weights.cashflow,
            },
            "currency": self.currency,
            "supplier_count": len(suppliers),
            "suppliers": suppliers,
            "recommended_supplier_id": self.recommended_supplier_id,
            "recommended_supplier_label": redact_secrets(self.label(self.recommended_supplier_id)),
            "reason_codes": list(self.analysis.reason_codes),
            "advisory_only": True,
            "negotiation": self._negotiation_dict(),
            "negotiation_unavailable_reason": self.negotiation_unavailable_reason,
            "draft_only": NEGOTIATION_DRAFT_ONLY,
            "external_send_supported": EXTERNAL_SEND_SUPPORTED,
            "external_sends": EXTERNAL_SENDS,
            "model_calls": MODEL_CALLS,
        }


def _display_amount(amount: Money) -> str:
    """Show the captured minor amount verbatim: no decimal-exponent assumption."""
    return f"{amount.amount_minor:,} {amount.currency}"


def _display_date(value: date | None) -> str:
    return value.isoformat() if value else UNKNOWN_LABEL


def _display_rank(value: int | None) -> str:
    return str(value) if value is not None else UNKNOWN_LABEL


def _display_terms(quote: SupplierQuote) -> str:
    terms = quote.payment_terms
    if terms is None:
        return UNKNOWN_LABEL
    if terms.prepaid:
        return f"{terms.label} (선급)"
    if terms.due_days is None:
        return f"{terms.label} (만기일 미확인)"
    return f"{terms.label} (만기 {terms.due_days}일)"


def _negotiation_message(
    *,
    supplier_label: str,
    target: NegotiationTarget,
    target_quote: SupplierQuote,
    competing_label: str,
    competing: SupplierQuote,
    competing_evidence: str,
) -> str:
    parts = [
        f"{supplier_label} 담당자님, 안녕하세요.",
        "",
        f"제시해 주신 견적 총액 {_display_amount(target.current_total)} 검토하였습니다.",
        f"동일 사양 비교 견적에서 {_display_amount(target.target_total)} 수준을 확인하였습니다.",
        f"- 비교 공급업체: {competing_label} (납기 {_display_date(competing.promised_delivery_date)})",
        f"- 산출 근거: {target.basis}",
    ]
    if competing_evidence:
        parts.append(f"- 확인 출처: {competing_evidence}")
    parts.extend(
        [
            "",
            (
                f"비교 견적 수준으로 총액을 {_display_amount(target.target_total)}까지"
                " 조정 가능 여부를 회신 부탁드립니다."
            ),
        ]
    )
    if target_quote.promised_delivery_date is not None:
        parts.append(
            f"현재 제시하신 납기 {target_quote.promised_delivery_date.isoformat()}의 유지 가능 여부도 확인 부탁드립니다."
        )
    terms = target_quote.payment_terms
    if terms is not None:
        parts.append(f"결제조건({terms.label}) 또한 유지 가능한지 함께 부탁드립니다.")
    parts.extend(
        [
            "",
            "[DRAFT ONLY — 발송 전 사용자 검토가 필요합니다. 본 초안은 자동 발송되지 않습니다.]",
        ]
    )
    message = "\n".join(parts)
    if len(message) > NEGOTIATION_MESSAGE_MAX_CHARS:
        return message[: NEGOTIATION_MESSAGE_MAX_CHARS - 1].rstrip() + "…"
    return message


def build_comparison_document(outcome: SupplierQuoteComparisonOutcome) -> str:
    """The deterministic Korean comparison report used as the artifact body."""
    analysis = outcome.analysis
    lines: list[str] = [
        "# 공급업체 견적 비교 — 결정론적 산출 결과",
        "",
        f"- 비교 모드: {analysis.mode.value}",
        (
            f"- 가중치: 가격 {analysis.weights.price} / 납기 {analysis.weights.delivery}"
            f" / 결제조건 {analysis.weights.cashflow}"
        ),
        f"- 통화: {outcome.currency} (입력한 최소 단위 금액을 그대로 표시)",
        f"- 비교 공급업체 수: {len(analysis.scores)}",
        "",
        "> 입력된 견적 항목만으로 계산되었습니다. 모델 추론·자동 발송·외부 쓰기는 사용되지 않았습니다.",
        "",
        "## 비교 표",
        "",
        "| 공급업체 | 품목 | 총액 | 납기 | 결제조건 | 가격순위 | 납기순위 | 현금흐름순위 | 점수(bp) | 미확인 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in analysis.scores:
        quote = outcome.quote_for(item.supplier_id)
        unknowns = ", ".join(item.unknown_fields) if item.unknown_fields else "-"
        lines.append(
            "| "
            + " | ".join(
                (
                    outcome.label(item.supplier_id),
                    outcome.item_labels.get(item.supplier_id, UNKNOWN_LABEL),
                    _display_amount(item.total),
                    _display_date(item.promised_delivery_date),
                    _display_terms(quote),
                    _display_rank(item.price_rank),
                    _display_rank(item.delivery_rank),
                    _display_rank(item.cashflow_rank),
                    str(item.score_basis_points),
                    unknowns,
                )
            )
            + " |"
        )

    winner = outcome.score_for(analysis.recommended_supplier_id)
    lowest = outcome.first_in_rank("price_rank")
    fastest = outcome.first_in_rank("delivery_rank")
    cashflow = outcome.first_in_rank("cashflow_rank")
    lines.extend(
        [
            "",
            "## 한정된 추천",
            "",
            f"- 추천 공급업체: {outcome.label(winner.supplier_id)} (`{winner.supplier_id}`)",
            f"- 추천 공급업체 견적 총액: {_display_amount(winner.total)}",
            f"- 산출 근거: {', '.join(analysis.reason_codes)}",
            "- 성격: 참조 전용(advisory_only). 확정 발주·자동 구매 권한이 없습니다.",
            "",
            "## 항목별 우위",
            "",
            f"- 최저가: {outcome.label(lowest.supplier_id) if lowest else UNKNOWN_LABEL}",
            f"- 최단 납기: {outcome.label(fastest.supplier_id) if fastest else UNKNOWN_LABEL}",
            f"- 현금흐름 유리: {outcome.label(cashflow.supplier_id) if cashflow else UNKNOWN_LABEL}",
            "",
            "## 미확인 항목",
            "",
        ]
    )
    incomplete = [item for item in analysis.scores if item.unknown_fields]
    if incomplete:
        lines.extend(f"- {outcome.label(item.supplier_id)}: {', '.join(item.unknown_fields)}" for item in incomplete)
    else:
        lines.append("- 없음")

    lines.extend(["", "## 협상 초안 (DRAFT ONLY)", ""])
    draft = outcome.negotiation
    target = outcome.negotiation_target
    if draft is None or target is None:
        reason = outcome.negotiation_unavailable_reason or NEGOTIATION_REASON_SINGLE_SUPPLIER
        lines.append(f"- 협상 초안 미생성: {reason}")
        lines.append("- 비교 견적이 없으면 협상 목표를 정할 수 없습니다. 값을 지어내지 않습니다.")
    else:
        lines.extend(
            [
                f"- 대상 공급업체: {outcome.label(target.supplier_id)} (`{target.supplier_id}`)",
                f"- 현재 총액: {_display_amount(target.current_total)}",
                f"- 목표 총액: {_display_amount(target.target_total)}",
                "- 근거: {}".format(target.basis),
                "",
                "### 협상 메시지 초안",
                "",
                draft.message,
                "",
                "- 상태: 작성 전용 초안입니다. 자동 발송되지 않으며 외부 전송 권한이 없습니다.",
            ]
        )
    lines.extend(
        [
            "",
            "---",
            "Padiem Claw · Deterministic Quote Comparison · Draft Only",
            "",
        ]
    )
    return "\n".join(lines)


def compare_supplier_quotes(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    engine: SupplierComparisonEngine | None = None,
) -> SupplierQuoteComparisonOutcome:
    """Run the existing deterministic engine over captured manual-intake quotes."""
    data = _mapping(payload, "invalid_payload", "request")

    workspace_id = _text(
        data.get("workspace_id"),
        "invalid_workspace_id",
        "workspace_id",
        limit=128,
        required=False,
    ) or DEFAULT_WORKSPACE_ID
    default_currency = _text(
        data.get("currency"), "invalid_currency", "currency", limit=3, required=False
    )
    if default_currency is not None:
        default_currency = default_currency.upper()
        if not re.fullmatch(r"[A-Z]{3}", default_currency):
            _fail("invalid_currency", "currency must be a 3-letter code")

    raw_mode = data.get("mode", ComparisonMode.BALANCED.value)
    if not isinstance(raw_mode, str) or raw_mode.strip().lower() not in _VALID_MODES:
        _fail("invalid_comparison_mode", f"mode must be one of: {', '.join(_VALID_MODES)}")
    mode = ComparisonMode(raw_mode.strip().lower())
    weights = _weights(data.get("weights"))

    raw_suppliers = data.get("suppliers")
    if not isinstance(raw_suppliers, Sequence) or isinstance(raw_suppliers, (str, bytes)):
        _fail("suppliers_required", "suppliers must be a non-empty list")
    if len(raw_suppliers) == 0:
        _fail("suppliers_required", "at least one supplier quote is required")
    if len(raw_suppliers) > MAX_SUPPLIERS:
        _fail("too_many_suppliers", f"suppliers must contain at most {MAX_SUPPLIERS} entries")

    stamp = received_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        _fail("invalid_supplier_entry", "received_at must be timezone-aware")

    quotes: list[SupplierQuote] = []
    supplier_labels: dict[str, str] = {}
    item_labels: dict[str, str] = {}
    for raw_entry in raw_suppliers:
        entry = _mapping(raw_entry, "invalid_supplier_entry", "supplier entry")
        if default_currency is not None and entry.get("currency") is None:
            entry = {**entry, "currency": default_currency}
        quote, label, item = _quote_from_entry(entry, workspace_id=workspace_id, received_at=stamp)
        quotes.append(quote)
        if quote.supplier_id in supplier_labels:
            _fail("invalid_supplier_id", "comparison accepts at most one quote per supplier")
        supplier_labels[quote.supplier_id] = label
        item_labels[quote.supplier_id] = item

    currencies = {quote.total.currency for quote in quotes}
    if len(currencies) != 1:
        _fail("mixed_currency", "all supplier quotes must use one currency")

    comparison_engine = engine if engine is not None else SupplierComparisonEngine()
    try:
        analysis = comparison_engine.evaluate(tuple(quotes), mode=mode, weights=weights)
    except ContractError as exc:
        _fail("comparison_unavailable", str(exc))

    draft, target, unavailable = _negotiation_for(
        quotes=tuple(quotes),
        mode=mode,
        workspace_id=workspace_id,
        supplier_labels=supplier_labels,
        comparison_engine=comparison_engine,
    )
    return SupplierQuoteComparisonOutcome(
        workspace_id=workspace_id,
        mode=mode,
        weights=weights if weights is not None else ComparisonWeights(),
        currency=quotes[0].total.currency,
        analysis=analysis,
        quotes=tuple(quotes),
        supplier_labels=supplier_labels,
        item_labels=item_labels,
        negotiation=draft,
        negotiation_target=target,
        negotiation_unavailable_reason=unavailable,
    )


def _weights(value: Any) -> ComparisonWeights | None:
    if value is None:
        return None
    raw = _mapping(value, "invalid_comparison_weights", "weights")
    try:
        return ComparisonWeights(
            price=_weight(raw.get("price", 50)),
            delivery=_weight(raw.get("delivery", 25)),
            cashflow=_weight(raw.get("cashflow", 25)),
        )
    except ContractError as exc:
        _fail("invalid_comparison_weights", str(exc))


def _weight(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("invalid_comparison_weights", "comparison weights must be integers")
    return value


def _negotiation_for(
    *,
    quotes: tuple[SupplierQuote, ...],
    mode: ComparisonMode,
    workspace_id: str,
    supplier_labels: Mapping[str, str],
    comparison_engine: SupplierComparisonEngine,
) -> tuple[NegotiationDraft | None, NegotiationTarget | None, str | None]:
    if len(quotes) < 2:
        return None, None, NEGOTIATION_REASON_SINGLE_SUPPLIER
    # Ask the most expensive captured supplier to match the cheapest captured
    # quote, so both ends of the target stay inside fields the user supplied.
    target_quote = max(quotes, key=lambda quote: (quote.total.amount_minor, quote.supplier_id))
    try:
        target = comparison_engine.negotiation_target_from_competing_quote(
            target_quote=target_quote,
            competing_quotes=quotes,
        )
    except ContractError:
        return None, None, NEGOTIATION_REASON_NO_COMPETING_QUOTE

    competing = min(
        (quote for quote in quotes if quote.supplier_id != target_quote.supplier_id),
        key=lambda quote: (quote.total.amount_minor, quote.supplier_id),
    )
    competing_evidence = competing.source_artifact.display_name if competing.source_artifact else ""
    message = _negotiation_message(
        supplier_label=supplier_labels.get(target_quote.supplier_id, target_quote.supplier_id),
        target=target,
        target_quote=target_quote,
        competing_label=supplier_labels.get(competing.supplier_id, competing.supplier_id),
        competing=competing,
        competing_evidence=competing_evidence,
    )
    draft = NegotiationDraft(
        negotiation_id=f"negotiation_{workspace_id}_{mode.value}",
        workspace_id=workspace_id,
        supplier_id=target.supplier_id,
        quote_id=target.quote_id,
        quote_version=target.quote_version,
        version=1,
        message=message,
        target_total=target.target_total,
    )
    return draft, target, None


__all__ = [
    "COMPARISON_DOCUMENT_TYPE",
    "DEFAULT_WORKSPACE_ID",
    "DETERMINISTIC_COMPARE",
    "EXTERNAL_SENDS",
    "EXTERNAL_SEND_SUPPORTED",
    "LLM_PRICE_INVENTION",
    "MAX_SUPPLIERS",
    "MODEL_CALLS",
    "NEGOTIATION_DRAFT_ONLY",
    "NEGOTIATION_REASON_NO_COMPETING_QUOTE",
    "NEGOTIATION_REASON_SINGLE_SUPPLIER",
    "OpsQuoteCompareFlowError",
    "PROVIDER_CALL_REQUIRED",
    "QUOTE_COMPARE_ERROR_CODES",
    "SupplierQuoteComparisonOutcome",
    "build_comparison_document",
    "compare_supplier_quotes",
]
