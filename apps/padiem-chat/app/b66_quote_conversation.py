"""B66 conversational variable extraction for assigned Saved Quote Skills (#3303).

The model is allowed to map one user utterance into bounded variable fields only.
It never calculates totals, mutates the assigned Saved Quote Skill, or renders a
quotation. QuoteCore + the approved B66 renderer remain the only calculation and
rendering authorities in the browser/runtime that consumes this projection.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Protocol

from .b66_quote_deterministic_fallback import parse_b66_mvp_fallback

MAX_CONVERSATION_CHARS = 4_000
MAX_RESULT_CHARS = 24_000
MAX_TEXT_CHARS = 2_000
MAX_MEMO_CHARS = 4_000
MAX_ITEMS = 100
MAX_ITEM_NAME_CHARS = 240
MAX_DETAIL_GROUPS = 32
MAX_DETAIL_ITEMS = 300
MAX_MODEL_WRAPPER_CHARS = 320

TAX_MODES = frozenset({"EXCLUSIVE", "INCLUSIVE", "EXEMPT"})
_ALLOWED_TOP = frozenset(
    {"recipient", "quoteNo", "issueDate", "projectName", "items", "detailGroups", "memo", "taxMode", "missing"}
)
_ALLOWED_RECIPIENT = frozenset({"company", "person", "address", "email"})
_ALLOWED_ITEM = frozenset({"name", "spec", "unit", "qty", "unitPrice", "note"})
_ALLOWED_DETAIL_GROUP = frozenset({"summaryIndex", "title", "items"})
_ALLOWED_DETAIL_ITEM = frozenset({"name", "spec", "unit", "qty", "unitPrice", "note", "section"})
_ALLOWED_MISSING = frozenset(
    {"recipient", "quoteNo", "issueDate", "items", "memo", "taxMode", "name", "qty", "unitPrice"}
)
_FORBIDDEN_KEYS = frozenset(
    {
        "subtotal",
        "supply",
        "supplyAmount",
        "vat",
        "vatAmount",
        "grand",
        "grandTotal",
        "total",
        "amount",
        "computedTotals",
        "template",
        "internalTemplate",
        "sender",
        "approval",
        "fingerprint",
    }
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMERIC_TEXT_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(\{.*\})\s*```$", re.IGNORECASE | re.DOTALL)
_JSON_FENCE_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
# Wrapper prose may not contain any structural character. A brace, bracket or
# fence in the wrapper means a second payload, an array or a stray fragment, and
# such output is rejected instead of parsed.
_STRUCTURAL_MARKERS = ("{", "}", "[", "]", "```")


class B66QuoteConversationError(ValueError):
    """Bounded conversation rejection.

    ``message`` is the stable rejection reason (e.g. ``invalid_number``).
    ``path`` is the offending field path and ``observed_type`` the JSON type
    name of the rejected value. Both are bounded structural labels only and
    never carry customer values or model text.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        observed_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.path = path
        self.observed_type = observed_type


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


class B66QuoteConversationClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Any | None = None,
        additional_system_context: str | None = None,
        attachments: tuple = (),
        model_id: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class B66QuoteConversationProjection:
    recipient: dict[str, str | None]
    quote_no: str | None
    issue_date: str | None
    items: tuple[dict[str, int | float | str], ...]
    memo: str | None
    tax_mode: str | None
    missing: tuple[str, ...]
    project_name: str | None = None
    detail_groups: tuple[dict[str, Any], ...] = ()
    # Server-owned provenance only. Never read from or serialize to quote facts.
    # "registered_model_completion" proves a validated B14 completion reached
    # this interpreter, NOT by itself a Google/provider-side POST receipt.
    result_origin: str = "unattributed"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "recipient": dict(self.recipient),
            "quoteNo": self.quote_no,
            "issueDate": self.issue_date,
            "projectName": self.project_name,
            "items": [dict(item) for item in self.items],
            "detailGroups": [
                {
                    **{key: value for key, value in group.items() if key != "items"},
                    "items": [dict(item) for item in group["items"]],
                }
                for group in self.detail_groups
            ],
            "memo": self.memo,
            "taxMode": self.tax_mode,
            "missing": list(self.missing),
        }


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in _FORBIDDEN_KEYS or _contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _optional_text(value: Any, *, limit: int, path: str | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise B66QuoteConversationError(
            "invalid_text", path=path, observed_type=_json_type_name(value)
        )
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > limit:
        raise B66QuoteConversationError("text_too_large", path=path, observed_type="string")
    return text


def _optional_number(
    value: Any, *, positive: bool, path: str | None = None
) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise B66QuoteConversationError("invalid_number", path=path, observed_type="boolean")
    if isinstance(value, str):
        text = value.strip()
        if not _NUMERIC_TEXT_RE.fullmatch(text):
            raise B66QuoteConversationError("invalid_number", path=path, observed_type="string")
        value = text
    elif not isinstance(value, (int, float)):
        raise B66QuoteConversationError(
            "invalid_number", path=path, observed_type=_json_type_name(value)
        )
    number = float(value)
    if not math.isfinite(number):
        raise B66QuoteConversationError(
            "invalid_number", path=path, observed_type=_json_type_name(value)
        )
    if positive and number <= 0:
        raise B66QuoteConversationError(
            "invalid_number", path=path, observed_type=_json_type_name(value)
        )
    if not positive and number < 0:
        raise B66QuoteConversationError(
            "invalid_number", path=path, observed_type=_json_type_name(value)
        )
    return int(number) if number.is_integer() else number


def _safe_wrapper_text(prefix: str, suffix: str) -> bool:
    """Return whether prose around one JSON payload is bounded and non-structural.

    The wrapper is commentary only. Bounding prefix and suffix together keeps one
    total prose budget, and forbidding structural characters keeps a second
    payload, an array or a stray fragment from being silently absorbed.
    """

    if len(prefix) + len(suffix) > MAX_MODEL_WRAPPER_CHARS:
        return False
    return not any(marker in prefix or marker in suffix for marker in _STRUCTURAL_MARKERS)


def _recover_single_json_payload(text: str) -> Any:
    """Deterministically recover one JSON value from one bounded prose wrapper.

    Exactly two shapes are accepted: a single fenced block, or a single raw JSON
    object that begins at the first structural character. There is no retry, no
    recursion and no second parse pass, so this cannot grow into an arbitrary
    substring scanner. Recovery only produces a candidate value; every field,
    authority and forbidden-key decision stays in ``normalize_conversation_output``.
    """

    fenced_blocks = list(_JSON_FENCE_BLOCK_RE.finditer(text))
    if fenced_blocks:
        if len(fenced_blocks) != 1:
            raise B66QuoteConversationError("invalid_model_output", path="answer.multiple_fences", observed_type="string")
        block = fenced_blocks[0]
        prefix = text[: block.start()].strip()
        suffix = text[block.end() :].strip()
        if not _safe_wrapper_text(prefix, suffix):
            raise B66QuoteConversationError("invalid_model_output", path="answer.unsafe_wrapper", observed_type="string")
        try:
            return json.loads(block.group(1).strip())
        except json.JSONDecodeError as exc:
            raise B66QuoteConversationError("invalid_model_output", path="answer.fenced_json_decode", observed_type="string") from exc

    start = text.find("{")
    if start < 0:
        raise B66QuoteConversationError("invalid_model_output", path="answer.no_json_object", observed_type="string")
    try:
        value, consumed = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise B66QuoteConversationError("invalid_model_output", path="answer.raw_json_decode", observed_type="string") from exc
    prefix = text[:start].strip()
    suffix = text[start + consumed :].strip()
    if not _safe_wrapper_text(prefix, suffix):
        raise B66QuoteConversationError("invalid_model_output", path="answer.unsafe_wrapper", observed_type="string")
    return value


def normalize_conversation_output(
    raw: Any, *, server_derives_missing: bool = False
) -> B66QuoteConversationProjection:
    """Validate model facts; optionally discard untrusted missing-field labels.

    In the live B66 interpreter, _server_missing_fields is authoritative.
    Preserve structural bounds and all quote fact/forbidden-field checks, but
    never reject a usable model answer merely because the model listed indexed
    or otherwise noncanonical missing-field names.
    """

    if isinstance(raw, str):
        if not raw:
            raise B66QuoteConversationError("invalid_model_output", path="answer.empty", observed_type="string")
        if len(raw) > MAX_RESULT_CHARS:
            raise B66QuoteConversationError("invalid_model_output", path="answer.too_large", observed_type="string")
        text = raw.strip()
        fenced = _JSON_FENCE_RE.fullmatch(text)
        if fenced is not None:
            # A whole-answer fence that still fails to parse is malformed model
            # output, not a wrapper to repair.
            try:
                raw = json.loads(fenced.group(1).strip())
            except json.JSONDecodeError as exc:
                raise B66QuoteConversationError("invalid_model_output", path="answer.fenced_json_decode", observed_type="string") from exc
        else:
            raw = _recover_single_json_payload(text)
    if not isinstance(raw, dict):
        raise B66QuoteConversationError(
            "invalid_model_output", path="top_level", observed_type=_json_type_name(raw)
        )
    if set(raw) - _ALLOWED_TOP:
        raise B66QuoteConversationError(
            "unsupported_output_field", path="top_level", observed_type="object"
        )
    if _contains_forbidden_key(raw):
        raise B66QuoteConversationError(
            "forbidden_output_field", path="top_level", observed_type="object"
        )

    recipient_raw = raw.get("recipient")
    if recipient_raw is None:
        recipient_raw = {}
    if not isinstance(recipient_raw, dict) or set(recipient_raw) - _ALLOWED_RECIPIENT:
        raise B66QuoteConversationError(
            "invalid_recipient", path="recipient", observed_type=_json_type_name(recipient_raw)
        )
    recipient = {}
    for key in ("company", "person", "address", "email"):
        recipient[key] = _optional_text(
            recipient_raw.get(key), limit=MAX_TEXT_CHARS, path=f"recipient.{key}"
        )

    quote_no = _optional_text(raw.get("quoteNo"), limit=120, path="quoteNo")
    issue_date = _optional_text(raw.get("issueDate"), limit=10, path="issueDate")
    if issue_date is not None:
        if not _ISO_DATE_RE.fullmatch(issue_date):
            raise B66QuoteConversationError("invalid_issue_date", path="issueDate", observed_type="string")
        try:
            date.fromisoformat(issue_date)
        except ValueError as exc:
            raise B66QuoteConversationError("invalid_issue_date", path="issueDate", observed_type="string") from exc

    items_raw = raw.get("items")
    if items_raw is None:
        items_raw = []
    if not isinstance(items_raw, list) or len(items_raw) > MAX_ITEMS:
        raise B66QuoteConversationError(
            "invalid_items", path="items", observed_type=_json_type_name(items_raw)
        )
    items: list[dict[str, Any]] = []
    missing_summary_prices: set[int] = set()
    for item_index, entry in enumerate(items_raw, start=1):
        if not isinstance(entry, dict) or set(entry) - _ALLOWED_ITEM:
            raise B66QuoteConversationError(
                "invalid_item", path=f"items[{item_index}]", observed_type=_json_type_name(entry)
            )
        item_path = f"items[{item_index}]"
        name = _optional_text(entry.get("name"), limit=MAX_ITEM_NAME_CHARS, path=f"{item_path}.name")
        spec = _optional_text(entry.get("spec"), limit=MAX_ITEM_NAME_CHARS, path=f"{item_path}.spec")
        unit = _optional_text(entry.get("unit"), limit=80, path=f"{item_path}.unit")
        qty = _optional_number(entry.get("qty"), positive=True, path=f"{item_path}.qty")
        unit_price = _optional_number(entry.get("unitPrice"), positive=False, path=f"{item_path}.unitPrice")
        note = _optional_text(entry.get("note"), limit=MAX_ITEM_NAME_CHARS, path=f"{item_path}.note")
        # Absent facts are partial input, not invalid facts. Preserve only
        # supplied values; neither the model nor this boundary supplies 0/1.
        item: dict[str, Any] = {}
        if name is not None:
            item["name"] = name
        if qty is not None:
            item["qty"] = qty
        if unit_price is None:
            missing_summary_prices.add(item_index)
        else:
            item["unitPrice"] = unit_price
        if spec is not None:
            item["spec"] = spec
        if unit is not None:
            item["unit"] = unit
        if note is not None:
            item["note"] = note
        items.append(item)

    detail_groups_raw = raw.get("detailGroups")
    if detail_groups_raw is None:
        detail_groups_raw = []
    if not isinstance(detail_groups_raw, list) or len(detail_groups_raw) > MAX_DETAIL_GROUPS:
        raise B66QuoteConversationError(
            "invalid_detail_groups", path="detailGroups", observed_type=_json_type_name(detail_groups_raw)
        )
    detail_groups: list[dict[str, Any]] = []
    seen_summary_indexes: set[int] = set()
    detail_item_count = 0
    for group_index, group_raw in enumerate(detail_groups_raw):
        if not isinstance(group_raw, dict) or set(group_raw) - _ALLOWED_DETAIL_GROUP:
            raise B66QuoteConversationError(
                "invalid_detail_group",
                path=f"detailGroups[{group_index}]",
                observed_type=_json_type_name(group_raw),
            )
        summary_index = group_raw.get("summaryIndex")
        if (
            isinstance(summary_index, bool)
            or not isinstance(summary_index, int)
            or summary_index < 1
            or summary_index > len(items)
            or summary_index in seen_summary_indexes
        ):
            raise B66QuoteConversationError(
                "invalid_detail_summary_index",
                path=f"detailGroups[{group_index}].summaryIndex",
                observed_type=_json_type_name(summary_index),
            )
        child_raw = group_raw.get("items")
        if not isinstance(child_raw, list) or not child_raw:
            raise B66QuoteConversationError(
                "invalid_detail_items",
                path=f"detailGroups[{group_index}].items",
                observed_type=_json_type_name(child_raw),
            )
        detail_item_count += len(child_raw)
        if detail_item_count > MAX_DETAIL_ITEMS:
            raise B66QuoteConversationError("too_many_detail_items", path="detailGroups", observed_type="array")
        child_items: list[dict[str, int | float | str]] = []
        for child_index, child in enumerate(child_raw, start=1):
            child_path = f"detailGroups[{group_index}].items[{child_index}]"
            if not isinstance(child, dict) or set(child) - _ALLOWED_DETAIL_ITEM:
                raise B66QuoteConversationError(
                    "invalid_detail_item", path=child_path, observed_type=_json_type_name(child)
                )
            name = _optional_text(child.get("name"), limit=MAX_ITEM_NAME_CHARS, path=f"{child_path}.name")
            spec = _optional_text(child.get("spec"), limit=MAX_ITEM_NAME_CHARS, path=f"{child_path}.spec")
            unit = _optional_text(child.get("unit"), limit=80, path=f"{child_path}.unit")
            qty = _optional_number(child.get("qty"), positive=True, path=f"{child_path}.qty")
            unit_price = _optional_number(child.get("unitPrice"), positive=False, path=f"{child_path}.unitPrice")
            note = _optional_text(child.get("note"), limit=MAX_ITEM_NAME_CHARS, path=f"{child_path}.note")
            section = _optional_text(child.get("section"), limit=MAX_ITEM_NAME_CHARS, path=f"{child_path}.section")
            child_item: dict[str, int | float | str] = {}
            for key, value in (("name", name), ("qty", qty), ("unitPrice", unit_price)):
                if value is not None:
                    child_item[key] = value
            if spec is not None:
                child_item["spec"] = spec
            if unit is not None:
                child_item["unit"] = unit
            if note is not None:
                child_item["note"] = note
            if section is not None:
                child_item["section"] = section
            child_items.append(child_item)
        group: dict[str, Any] = {
            "id": f"detail-group-{group_index + 1}",
            "summaryItemId": f"item-{summary_index}",
            "items": child_items,
        }
        title = _optional_text(
            group_raw.get("title"), limit=MAX_ITEM_NAME_CHARS, path=f"detailGroups[{group_index}].title"
        )
        if title is not None:
            group["title"] = title
        detail_groups.append(group)
        seen_summary_indexes.add(summary_index)

    for summary_index in missing_summary_prices:
        if summary_index not in seen_summary_indexes:
            # 요약 단가도 detailGroup 도 없는 item 은 partial 로 보존한다.
            # 값을 추정하거나 계산하지 않고 unitPrice 키를 비워 두며,
            # 최종 검증(QuoteCore/Skill build)에서는 여전히 거부된다.
            continue
        # Detail-group subtotal is the authority. Zero is only a non-authoritative
        # placeholder required by the existing structured-input item contract.
        items[summary_index - 1]["unitPrice"] = 0

    project_name = _optional_text(raw.get("projectName"), limit=MAX_ITEM_NAME_CHARS, path="projectName")
    memo = _optional_text(raw.get("memo"), limit=MAX_MEMO_CHARS, path="memo")
    tax_mode_raw = raw.get("taxMode")
    if tax_mode_raw is None:
        tax_mode = None
    elif not isinstance(tax_mode_raw, str):
        raise B66QuoteConversationError(
            "invalid_tax_mode", path="taxMode", observed_type=_json_type_name(tax_mode_raw)
        )
    else:
        tax_mode = tax_mode_raw.strip().upper()
        if tax_mode not in TAX_MODES:
            raise B66QuoteConversationError("invalid_tax_mode", path="taxMode", observed_type="string")

    # During model-backed extraction the provider's "missing" field has no
    # authority. Its labels, duplicates or even its container shape must not
    # reject otherwise valid customer facts. The answer-size guard and all
    # forbidden-key/fact validators still run before this point.
    # The interpreter recomputes missing from approved Saved Skill facts.
    missing_raw = [] if server_derives_missing else raw.get("missing")
    if missing_raw is None:
        missing_raw = []
    if (
        not isinstance(missing_raw, list)
        or len(missing_raw) > len(_ALLOWED_MISSING)
        or any(not isinstance(item, str) or item not in _ALLOWED_MISSING for item in missing_raw)
        or len(set(missing_raw)) != len(missing_raw)
    ):
        raise B66QuoteConversationError(
            "invalid_missing_fields", path="missing", observed_type=_json_type_name(missing_raw)
        )

    return B66QuoteConversationProjection(
        recipient=recipient,
        quote_no=quote_no,
        issue_date=issue_date,
        items=tuple(items),
        memo=memo,
        tax_mode=tax_mode,
        missing=tuple(missing_raw),
        project_name=project_name,
        detail_groups=tuple(detail_groups),
    )


def _conversation_prompt(skill: dict[str, Any]) -> str:
    if not isinstance(skill, dict):
        raise B66QuoteConversationError("invalid_saved_skill")
    variable_schema = skill.get("variableSchema")
    fixed_defaults = skill.get("fixedDefaults")
    if not isinstance(variable_schema, dict) or not isinstance(fixed_defaults, dict):
        raise B66QuoteConversationError("invalid_saved_skill")

    allowed = [
        key
        for key in ("recipient", "quoteNo", "issueDate", "items", "memo", "taxMode")
        if variable_schema.get(key) is True
    ]
    if not allowed:
        raise B66QuoteConversationError("invalid_saved_skill")

    default_tax = fixed_defaults.get("taxMode")
    if default_tax not in TAX_MODES:
        default_tax = None

    contract = {
        "allowedVariableFields": allowed,
        "optionalPresentationFields": [
            "projectName",
            "items.spec",
            "items.unit",
            "items.note",
            "detailGroups[].summaryIndex",
            "detailGroups[].title",
            "detailGroups[].items[].section",
            "detailGroups[].items[].spec",
            "detailGroups[].items[].unit",
            "detailGroups[].items[].note",
        ],
        "defaultTaxMode": default_tax,
    }
    return (
        "당신은 견적서 생성기가 아니라 견적 입력값 추출기입니다. "
        "사용자의 한 문장에서 실제로 말한 값만 JSON 객체 하나로 추출하십시오. "
        "고객의 일상적인 띄어쓰기, 조사 오류나 분명한 철자 오타는 문맥상 의미가 하나로 확실한 경우에만 해석하십시오. "
        "뜻이 여러 개이거나 업체명, 담당자명, 품목명처럼 고객이 확인해야 할 고유 정보가 불명확하면 추측하지 말고 해당 값은 null로 두십시오. "
        "수량, 단가, 세금 조건은 임의로 만들거나 유추한 숫자로 채우지 마십시오. "
        "약, 대충, 정도, 내외, 범위로 표현한 수량은 확정 숫자가 아니므로 null로 두고 고객에게 정확한 수량을 다시 확인하십시오. "
        "정보가 불분명하면 다른 필드의 확실한 사실은 보존하고 불분명한 필드만 null로 두어 서비스가 고객에게 다시 질문하게 하십시오. "
        "최상위 키는 recipient, quoteNo, issueDate, projectName, items, detailGroups, memo, taxMode, missing 만 허용됩니다. "
        "recipient는 company/person/address/email을 사용하십시오. "
        "items는 name/spec/unit/qty/unitPrice/note 만 사용하십시오. "
        "사용자가 건명을 말하면 projectName에 그대로 넣으십시오. "
        "품목명이 원문에 명확히 나타나면 내부 공백·숫자·단위 접미사까지 원문 그대로 복사하십시오. "
        "예를 들어 원문이 '부품 01호'라면 '부품 01 호'로 바꾸지 마십시오. "
        "원문 품목명이 불명확하면 임의로 공백을 붙이거나 지우지 말고 이름만 null로 두십시오. "
        "상세내역을 말한 경우 detailGroups 배열을 사용하고 각 그룹은 summaryIndex/title/items만 사용하십시오. "
        "summaryIndex는 연결할 요약 items의 1부터 시작하는 순번입니다. "
        "상세 그룹이 연결된 요약 item의 단가를 사용자가 말하지 않았다면 계산하지 말고 unitPrice를 null로 두십시오. "
        "서버와 QuoteCore가 상세 소계를 요약 단가로 파생합니다. "
        "상세 items는 name/spec/unit/qty/unitPrice/note/section만 사용하십시오. "
        "금액 합계, 공급가액, 부가세 금액, 총액을 계산하거나 반환하지 마십시오. "
        "sender, template, approval, fingerprint를 변경하거나 반환하지 마십시오. "
        "알 수 없는 필수 값은 null 또는 빈 배열로 두십시오. missing은 서비스가 검증된 값에서 직접 계산하므로 빈 배열 []을 사용하십시오. "
        "설명/마크다운 없이 JSON만 반환하십시오. "
        "아래 서버 제공 계약 밖 필드는 추출하지 마십시오.\n"
        + json.dumps(contract, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def _server_missing_fields(
    projection: B66QuoteConversationProjection,
    skill: dict[str, Any],
) -> tuple[str, ...]:
    """Derive required missing fields from normalized facts, never model claims."""

    schema = skill.get("variableSchema")
    if not isinstance(schema, dict):
        raise B66QuoteConversationError("invalid_saved_skill")
    missing: list[str] = []
    if schema.get("recipient") is True and not (
        projection.recipient.get("company") or projection.recipient.get("person")
    ):
        missing.append("recipient")
    # quoteNo and issueDate are intentionally not conversational blockers.
    # The canonical browser QuoteCore supplies today's date and its default
    # quote-number pattern when the user does not explicitly say them.
    if schema.get("items") is True and not projection.items:
        missing.append("items")
    if schema.get("items") is True and projection.items:
        # Summary and detail facts share the same partial-input contract.
        # A linked summary price is derived by QuoteCore; every other absent
        # required fact must be supplied before a final draft can be built.
        required_items = list(projection.items) + [
            item for group in projection.detail_groups for item in group["items"]
        ]
        for field in ("name", "qty", "unitPrice"):
            if any(field not in item for item in required_items):
                missing.append(field)
    return tuple(missing)


# Owner #3916: customer-authored quantity qualifiers outrank a model's numeric
# projection. This is a finalization guard, not a new extraction authority.
# Match number+quantity unit only; a price such as "약 2만원" is not quantity.
_QUANTITY_UNIT_RE = r"(?:미터|박스|세트|묶음|kg|KG|mm|cm|m2|EA|ea|개|대|장|톤|식|본|롤|통|병|쌍|건|벌|포|m|M|㎡)"
_QUANTITY_NUMBER_RE = r"(?:\d{1,6}(?:,\d{3})*(?:\.\d+)?)"
_QUANTITY_PHRASE_RE = re.compile(
    rf"(?P<qualifier>약|대략|대충|한)?\s*"
    rf"(?P<lower>{_QUANTITY_NUMBER_RE})\s*"
    rf"(?:(?:~|～|∼|-)\s*(?P<upper>{_QUANTITY_NUMBER_RE})\s*)?"
    rf"(?P<unit>{_QUANTITY_UNIT_RE})\s*"
    rf"(?P<suffix>정도|쯤|내외|가량|안팎)?"
)


def _bounded_quantity_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value.replace(",", "") if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _guard_unconfirmed_approximate_quantities(
    message: str, projection: B66QuoteConversationProjection
) -> B66QuoteConversationProjection:
    """Do not let approximate source quantities become finalized QuoteCore facts.

    The browser's existing bounded follow-up sends the original message and
    customer-only "답변:" lines. A numerical, unqualified quantity in one of
    those answer lines is the ONLY confirmation allowed here. An unqualified
    "네" is intentionally insufficient: the customer must restate a quantity.
    Neither the model's missing metadata nor generated question text can
    authorize confirmation.
    """
    original = message.split("\n추가 질문:", 1)[0]
    approximate = [
        hit for hit in _QUANTITY_PHRASE_RE.finditer(original)
        if hit.group("qualifier") or hit.group("upper") or hit.group("suffix")
    ]
    if not approximate:
        return projection

    estimates: set[float] = set()
    for hit in approximate:
        for key in ("lower", "upper"):
            if hit.group(key):
                value = _bounded_quantity_number(hit.group(key))
                if value is not None:
                    estimates.add(value)

    # Deliberately do not trust numeric text in the initial estimate or in a
    # model-generated "추가 질문:"; only explicit subsequent user replies.
    confirmed: set[float] = set()
    for answer in re.findall(r"(?:^|\n)답변:\s*([^\n]{0,1000})", message):
        for hit in _QUANTITY_PHRASE_RE.finditer(answer):
            if hit.group("qualifier") or hit.group("upper") or hit.group("suffix"):
                continue
            value = _bounded_quantity_number(hit.group("lower"))
            if value is not None:
                confirmed.add(value)

    # Prefer the item name immediately preceding each rough quantity within
    # the same comma-delimited phrase. This preserves independent exact items
    # even when the customer later confirms a DIFFERENT count. If attribution
    # is unclear, fail closed instead of trusting any numeric model guess.
    all_items = list(projection.items) + [
        item for group in projection.detail_groups for item in group["items"]
    ]
    blocked: set[int] = set()
    for hit in approximate:
        local = original[max(0, hit.start() - 100):hit.start()]
        local = re.split(r"[,，;\n]", local)[-1]
        names = [
            (local.rfind(item["name"]), idx)
            for idx, item in enumerate(all_items)
            if isinstance(item.get("name"), str) and item["name"] in local
        ]
        if names:
            blocked.add(max(names)[1])
            continue
        span_values = {
            _bounded_quantity_number(hit.group(key))
            for key in ("lower", "upper") if hit.group(key)
        }
        matching = [
            idx for idx, item in enumerate(all_items)
            if _bounded_quantity_number(item.get("qty")) in span_values
        ]
        if matching:
            blocked.update(matching)
        else:
            blocked.update(range(len(all_items)))

    modified = False

    def guard_item(item: dict[str, Any], idx: int) -> dict[str, Any]:
        nonlocal modified
        copy = dict(item)
        if idx in blocked and "qty" in copy:
            value = _bounded_quantity_number(copy["qty"])
            if value not in confirmed:
                del copy["qty"]
                modified = True
        return copy

    items = tuple(guard_item(item, idx) for idx, item in enumerate(projection.items))
    offset = len(projection.items)
    groups = []
    for group in projection.detail_groups:
        group_items = [
            guard_item(item, offset + idx)
            for idx, item in enumerate(group["items"])
        ]
        offset += len(group_items)
        groups.append({**group, "items": group_items})
    return replace(projection, items=items, detail_groups=tuple(groups)) if modified else projection


def _recover_unambiguous_single_item_quantity(
    message: str, projection: B66QuoteConversationProjection
) -> B66QuoteConversationProjection:
    """Recover ONE *exact customer-stated* quantity omitted by B14.

    #3733: a live model returned qty missing even though the customer said
    "배관 100미터". This deterministic repair uses the customer utterance,
    not a model's numeric estimate. Only one named item and one unqualified,
    contiguous number+unit are eligible. All uncertain cases remain missing.
    Follow-up messages cannot silently override a later customer correction.
    """
    if len(projection.items) != 1 or projection.detail_groups or "\n추가 질문:" in message:
        return projection
    item = projection.items[0]
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return projection
    matches = list(_QUANTITY_PHRASE_RE.finditer(message))
    if len(matches) != 1:
        return projection
    hit = matches[0]
    if hit.group("qualifier") or hit.group("upper") or hit.group("suffix"):
        return projection
    # Don't mistake a unit prefix of another token ("mL", "EA123") for a
    # complete quantity unit. Ambiguous suffixes are never filled in.
    if hit.end() < len(message) and message[hit.end()].isalnum():
        return projection
    local = re.split(r"[,，;\n]", message[max(0, hit.start() - 100):hit.start()])[-1]
    if name not in local:
        return projection
    quantity = _bounded_quantity_number(hit.group("lower"))
    if quantity is None or quantity <= 0 or quantity > 999999:
        return projection
    current = _bounded_quantity_number(item.get("qty"))
    if current is not None and current == quantity:
        return projection
    updated = dict(item)
    if current is None:
        # The customer stated this number exactly. No price, tax or any other
        # field is inferred; the existing missing-field gate still applies.
        updated["qty"] = int(quantity) if quantity.is_integer() else quantity
    else:
        # Model output contradicted a single explicit customer count. Reject
        # the inconsistent model quantity rather than choose a number silently.
        updated.pop("qty", None)
    return replace(projection, items=(updated,))


class B66QuoteConversationInterpreter:
    """One bounded model call for variable extraction only."""

    def __init__(self, client: B66QuoteConversationClient):
        if client is None:
            raise ValueError("B14 client is required")
        self._client = client

    async def interpret(
        self,
        *,
        message: str,
        skill: dict[str, Any],
        model_id: str | None = None,
    ) -> B66QuoteConversationProjection:
        if not isinstance(message, str):
            raise B66QuoteConversationError("invalid_message")
        clean = message.strip()
        if not clean or len(clean) > MAX_CONVERSATION_CHARS:
            raise B66QuoteConversationError("invalid_message")
        prompt = _conversation_prompt(skill)
        try:
            # Legacy isolated quote parser clients keep their original
            # completion shape. Production B66 passes the selected exact ID
            # as a separate keyword, never extracted from customer text.
            selected_kw = {"model_id": model_id} if model_id is not None else {}
            result = await self._client.complete(
                [{"role": "user", "content": clean}],
                additional_system_context=prompt,
                attachments=(),
                **selected_kw,
            )
        except Exception as exc:
            # First-MVP resilience boundary (#3391): keep every existing
            # runtime/error contract except the exact Production blocker
            # observed on the current B66 lane. Only a projected provider 5xx
            # may enter the narrow deterministic Korean quote grammar.
            if getattr(exc, "code", None) != "provider_server_error":
                raise
            schema = skill.get("variableSchema")
            if (
                not isinstance(schema, dict)
                or schema.get("recipient") is not True
                or schema.get("items") is not True
            ):
                raise
            raw_fallback = parse_b66_mvp_fallback(clean)
            if raw_fallback is None:
                raise
            if schema.get("taxMode") is not True:
                raw_fallback.pop("taxMode", None)
            projection = normalize_conversation_output(raw_fallback)
            projection = _guard_unconfirmed_approximate_quantities(clean, projection)
            projection = _recover_unambiguous_single_item_quantity(clean, projection)
            return replace(
                projection,
                missing=_server_missing_fields(projection, skill),
                result_origin="deterministic_fallback",
            )
        if not isinstance(result, dict):
            raise B66QuoteConversationError("invalid_model_output")
        answer = result.get("answer")
        if not isinstance(answer, str):
            raise B66QuoteConversationError("invalid_model_output")
        projection = normalize_conversation_output(answer, server_derives_missing=True)
        projection = _guard_unconfirmed_approximate_quantities(clean, projection)
        projection = _recover_unambiguous_single_item_quantity(clean, projection)
        return replace(
            projection,
            missing=_server_missing_fields(projection, skill),
            result_origin="registered_model_completion",
        )