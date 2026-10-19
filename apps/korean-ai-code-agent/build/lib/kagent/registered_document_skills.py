"""#2014: 견적서/발주서 flows as Core-registered Skill packages (스킬화).

Claw's first business use case (#1878 A) reaches its intended shape — "받아와서
그걸 스킬로 만들고 그 스킬에 의해서 앞으로 내용만 말하면 견적서 만드는거지"
(owner, 2026-09-06). The 견적서/발주서 draft flows stop being ad-hoc CLI
invocations and become **registered Skill packages** whose declared input is
free-form request text.

What this module is, precisely
------------------------------
* It is a **declarative registration surface**. It builds ``ReusableSkillPackage``
  values and registers them into a ``SkillRegistrySnapshot`` plus a
  ``SkillInstallationSnapshot`` using the Core skill machinery **as a consumer**.
  Core is not modified here.
* It is **not** a runtime. Skill execution authority lives in P01/Core
  (Engine-side ``agent_skill_service``), whose kagent-facing wire is not yet
  available — see ``ENGINE_RUNTIME_READY`` below.
* It makes **no provider call, no credential use, no storage/DB mutation, and
  no deployment action**. Building these values is pure local computation.

Free-form intake ("내용만 말하면")
----------------------------------
The skills declare ``FREE_FORM_REQUEST_INPUT_CONTRACT_REF`` as their input
contract: the intake is **free-form request text**, not a hand-written input
file. Text already extracted by the document-intake slice (#2013/#2012; #1957
review pattern) may accompany the request as ``attachment_texts``, but is never
required. When ``doc_type`` is omitted the intake resolves it from the request
text deterministically and **fails closed** when the text is silent
(``freeform_doc_type_unresolved``) or mentions both document types
(``freeform_doc_type_ambiguous``).

Engine-side dependency (#1969 / #1971)
--------------------------------------
``apps/korean-ai-code-agent/src/kagent/p01_orchestration_client.py`` lists
``skill_id``, ``skill_registry``, ``skill_installations`` and
``skill_runtime_policy`` in ``_NULLABLE_AUTHORITY_FIELDS`` — authority the
**public P01 wire cannot round-trip losslessly**, so the port refuses any
request carrying them with ``p01_authority_field_unsupported``. That is the
concrete, executable reason registered skills cannot yet be dispatched through
P01: the local registration/catalogue/intake path works today, while
Engine-side skill execution waits on the E9 series (#1969 — CLOSED/COMPLETED;
#1971 — OPEN). This module therefore records ``ENGINE_RUNTIME_READY = False``
and implements no Engine runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sys
from typing import Any

from padiem_ai_core.skill_package import (
    ApprovalHook,
    ReusableSkillPackage,
    SkillExecutionBudget,
)
from padiem_ai_core.skill_registry import (
    SkillInstallation,
    SkillInstallationSnapshot,
    SkillInstallStatus,
    SkillRegistrySnapshot,
    resolve_enabled_skill,
)

from .contracts import ContractError
from .core import redact_secrets
from .draft_flow import DRAFT_DOC_TYPES

SKILL_PUBLISHER_ID = "kagent.b54"

CUSTOMER_QUOTE_SKILL_ID = "skill:kagent.b54:customer-quote-draft@1"
PURCHASE_ORDER_SKILL_ID = "skill:kagent.b54:purchase-order-draft@1"

CUSTOMER_QUOTE_DOC_TYPE = "견적서"
PURCHASE_ORDER_DOC_TYPE = "발주서"

FREE_FORM_REQUEST_INPUT_CONTRACT_REF = "contract:kagent/claw/freeform-document-request@1"
CUSTOMER_QUOTE_OUTPUT_CONTRACT_REF = "contract:kagent/claw/customer-quote-draft@1"
PURCHASE_ORDER_OUTPUT_CONTRACT_REF = "contract:kagent/claw/purchase-order-draft@1"

DOCUMENT_DRAFT_CAPABILITY = "document_draft"

DEFAULT_SKILL_APP_ID = "korean-ai-code-agent"
DEFAULT_SKILL_SUBJECT_ID = "local-cli"

MAX_FREEFORM_REQUEST_CHARS = 20_000
MAX_FREEFORM_ATTACHMENTS = 8

ENGINE_RUNTIME_READY = False
ENGINE_RUNTIME_DEPENDENCIES = ("#1969", "#1971")
ENGINE_RUNTIME_BLOCKER_CODE = "p01_authority_field_unsupported"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_DOC_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    CUSTOMER_QUOTE_DOC_TYPE: ("견적", "견적서", "quote", "quotation", "단가"),
    PURCHASE_ORDER_DOC_TYPE: ("발주", "발주서", "주문", "order", "purchase order"),
}


def _freeform_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ContractError(f"{field_name} is required")
    if len(normalized) > MAX_FREEFORM_REQUEST_CHARS:
        raise ContractError(f"{field_name} exceeds {MAX_FREEFORM_REQUEST_CHARS} characters")
    if _CONTROL_RE.search(normalized):
        raise ContractError(f"{field_name} contains forbidden control characters")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _validate_doc_type(value: Any) -> str:
    if not isinstance(value, str) or value not in DRAFT_DOC_TYPES:
        allowed = ", ".join(DRAFT_DOC_TYPES)
        raise ContractError(f"doc_type must be one of {allowed}")
    return value


def _validate_channel(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError("channel must be a bounded safe identifier")
    return value.strip()


def resolve_request_doc_type(request_text: str, doc_type: str | None = None) -> str:
    """Resolve the target document type from free-form request text.

    An explicit ``doc_type`` always wins. Otherwise the text is scanned for the
    deterministic keyword sets; silence and ambiguity both fail closed rather
    than guessing, because a mis-routed 견적서/발주서 produces a document with
    the wrong legal shape.
    """

    if doc_type is not None:
        return _validate_doc_type(doc_type)
    if not isinstance(request_text, str):
        raise ContractError("request_text must be a string")
    haystack = request_text.casefold()
    matched = tuple(
        candidate
        for candidate, keywords in _DOC_TYPE_KEYWORDS.items()
        if any(keyword.casefold() in haystack for keyword in keywords)
    )
    if not matched:
        raise ContractError(
            "freeform_doc_type_unresolved: 요청 텍스트에서 문서 유형(견적서/발주서)을 "
            "확정할 수 없습니다 — --doc-type 으로 지정하십시오."
        )
    if len(matched) > 1:
        raise ContractError(
            "freeform_doc_type_ambiguous: 요청 텍스트가 두 문서 유형을 함께 언급합니다 "
            "— --doc-type 으로 지정하십시오."
        )
    return matched[0]


@dataclass(frozen=True, slots=True)
class SkillRequestIntake:
    """#2014 free-form request intake — the declared Skill input contract.

    ``request_text`` is the whole point of the slice: the caller describes the
    deal in ordinary Korean ("거래처 A에 품목 3종 견적서 뽑아줘") and the Skill
    resolves the document type and carries the text into the flow. No
    hand-written input file is part of the contract.
    """

    request_text: str
    doc_type: str | None = None
    attachment_texts: tuple[str, ...] = ()
    channel: str = "freeform"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_text", _freeform_text(self.request_text, "request_text")
        )
        if self.doc_type is not None:
            object.__setattr__(self, "doc_type", _validate_doc_type(self.doc_type))
        if not isinstance(self.attachment_texts, tuple):
            raise ContractError("attachment_texts must be a tuple")
        if len(self.attachment_texts) > MAX_FREEFORM_ATTACHMENTS:
            raise ContractError(
                f"attachment_texts exceeds {MAX_FREEFORM_ATTACHMENTS} entries"
            )
        object.__setattr__(
            self,
            "attachment_texts",
            tuple(
                _freeform_text(text, f"attachment_texts[{index}]", allow_empty=True)
                for index, text in enumerate(self.attachment_texts)
            ),
        )
        object.__setattr__(self, "channel", _validate_channel(self.channel))

    @property
    def resolved_doc_type(self) -> str:
        return resolve_request_doc_type(self.request_text, self.doc_type)

    def to_input_payload(self) -> dict[str, Any]:
        """Return the bounded dict handed to the Skill as its input."""

        return {
            "contract": FREE_FORM_REQUEST_INPUT_CONTRACT_REF,
            "doc_type": self.resolved_doc_type,
            "request_text": self.request_text,
            "channel": self.channel,
            "attachments": [
                {"index": index, "text": text}
                for index, text in enumerate(self.attachment_texts)
                if text
            ],
        }


def _anti_hallucination_clause() -> str:
    return (
        "금액·단가·수량·합계를 절대 추측하지 마십시오. 입력(요청 텍스트 및 첨부 추출 "
        "텍스트)에 근거가 없는 값은 반드시 \"입력 필요\"로 명기합니다. 합계는 흐름이 "
        "수량×단가 정수 연산으로 계산한 값만 사용합니다."
    )


def _no_send_clause() -> str:
    return (
        "결과는 DRAFT(초안)이며 어떠한 외부 채널(이메일·카카오·SMS·메신저)로도 "
        "전송하지 않습니다. 전송은 별도 승인 경로의 몫입니다."
    )


_CUSTOMER_QUOTE_INSTRUCTION = (
    "역할: 자유 서술 요청 텍스트에서 거래 맥락을 추출해 견적서 초안을 작성합니다.\n"
    "\n"
    "1단계(추출): 요청 텍스트와 첨부 추출 텍스트에서 공급자·공급받는 자·품목·수량·"
    "단가·조건을 짧은 구조화 필드로 추출합니다.\n"
    "2단계(계산): 흐름이 합계 = Σ(수량 × 단가)를 정수 연산으로 계산합니다.\n"
    "3단계(작성): 공급받는 자 / 공급자 / 품목·수량·단가 / 합계 / 조건 순서로 초안 본문을 "
    "작성합니다.\n"
    "\n"
    f"제약: {_anti_hallucination_clause()}\n"
    f"제약: {_no_send_clause()}\n"
    "제약: 문서 머리에 DRAFT(초안) 표기를 유지합니다.\n"
)

_PURCHASE_ORDER_INSTRUCTION = (
    "역할: 자유 서술 요청 텍스트에서 발주 맥락을 추출해 발주서 초안을 작성합니다.\n"
    "\n"
    "1단계(추출): 요청 텍스트와 첨부 추출 텍스트에서 발주자·공급처·품목·수량·납기·"
    "특이조건을 짧은 구조화 필드로 추출합니다.\n"
    "2단계(계산): 수량·단가 근거가 있는 항목만 정수 연산으로 합계를 계산합니다.\n"
    "3단계(작성): 발주자 / 공급처 / 품목·수량·납기 / 특이조건 순서로 초안 본문을 "
    "작성합니다.\n"
    "\n"
    f"제약: {_anti_hallucination_clause()}\n"
    f"제약: {_no_send_clause()}\n"
    "제약: 문서 머리에 DRAFT(초안) 표기를 유지합니다.\n"
)


CUSTOMER_QUOTE_SKILL = ReusableSkillPackage(
    skill_id=CUSTOMER_QUOTE_SKILL_ID,
    publisher_id=SKILL_PUBLISHER_ID,
    description=(
        "자유 서술 요청 텍스트(거래처·품목·수량·단가·조건)를 받아 견적서 초안(DRAFT)을 "
        "만듭니다. 합계는 흐름이 수량×단가 정수 연산으로 계산하고, 근거 없는 금액은 "
        "\"입력 필요\"로 남깁니다. 초안은 어디로도 전송되지 않습니다."
    ),
    instruction=_CUSTOMER_QUOTE_INSTRUCTION,
    input_contract_ref=FREE_FORM_REQUEST_INPUT_CONTRACT_REF,
    output_contract_ref=CUSTOMER_QUOTE_OUTPUT_CONTRACT_REF,
    required_capabilities=(DOCUMENT_DRAFT_CAPABILITY,),
    allowed_tool_ids=(),
    connector_requirement_ids=(),
    context_policy_ref="context:default",
    model_policy_ref="model:auto",
    execution_budget=SkillExecutionBudget(
        max_steps=2, max_tool_calls=0, max_wall_seconds=120
    ),
    approval_hooks=(ApprovalHook.BEFORE_EXTERNAL_SIDE_EFFECT,),
)


PURCHASE_ORDER_SKILL = ReusableSkillPackage(
    skill_id=PURCHASE_ORDER_SKILL_ID,
    publisher_id=SKILL_PUBLISHER_ID,
    description=(
        "자유 서술 요청 텍스트(발주자·공급처·품목·수량·납기·특이조건)를 받아 발주서 "
        "초안(DRAFT)을 만듭니다. 근거 없는 수량·금액은 \"입력 필요\"로 남깁니다. 초안은 "
        "어디로도 전송되지 않습니다."
    ),
    instruction=_PURCHASE_ORDER_INSTRUCTION,
    input_contract_ref=FREE_FORM_REQUEST_INPUT_CONTRACT_REF,
    output_contract_ref=PURCHASE_ORDER_OUTPUT_CONTRACT_REF,
    required_capabilities=(DOCUMENT_DRAFT_CAPABILITY,),
    allowed_tool_ids=(),
    connector_requirement_ids=(),
    context_policy_ref="context:default",
    model_policy_ref="model:auto",
    execution_budget=SkillExecutionBudget(
        max_steps=2, max_tool_calls=0, max_wall_seconds=120
    ),
    approval_hooks=(ApprovalHook.BEFORE_EXTERNAL_SIDE_EFFECT,),
)


DOCUMENT_SKILL_PACKAGES: tuple[ReusableSkillPackage, ...] = (
    CUSTOMER_QUOTE_SKILL,
    PURCHASE_ORDER_SKILL,
)

DOCUMENT_SKILL_BY_DOC_TYPE: dict[str, ReusableSkillPackage] = {
    CUSTOMER_QUOTE_DOC_TYPE: CUSTOMER_QUOTE_SKILL,
    PURCHASE_ORDER_DOC_TYPE: PURCHASE_ORDER_SKILL,
}


def build_document_skill_registry() -> SkillRegistrySnapshot:
    """Register both document Skills into an immutable Core registry snapshot.

    This is the registration act. ``SkillRegistrySnapshot.from_packages``
    enforces canonical-id shape, fingerprint identity and sort order, so the
    returned snapshot is already Core-validated.
    """

    return SkillRegistrySnapshot.from_packages(DOCUMENT_SKILL_PACKAGES)


def build_document_skill_installations(
    app_id: str = DEFAULT_SKILL_APP_ID,
    subject_id: str = DEFAULT_SKILL_SUBJECT_ID,
) -> SkillInstallationSnapshot:
    """Return installation state marking both Skills ENABLED for this product.

    Installation state is explicitly **non-authoritative** (Core contract): it
    never substitutes for trusted grants, and resolution still has to pass
    through ``compile_skill_profile`` with a trusted runtime policy before any
    execution. Declared here only so the catalogue can prove the Skills are
    resolvable end-to-end.
    """

    return SkillInstallationSnapshot.from_installations(
        SkillInstallation(
            app_id=app_id,
            subject_id=subject_id,
            skill_id=package.skill_id,
            status=SkillInstallStatus.ENABLED,
        )
        for package in DOCUMENT_SKILL_PACKAGES
    )


def resolve_document_skill(
    skill_id: str,
    *,
    app_id: str = DEFAULT_SKILL_APP_ID,
    subject_id: str = DEFAULT_SKILL_SUBJECT_ID,
) -> ReusableSkillPackage:
    """Resolve an ENABLED document Skill package by canonical id."""

    return resolve_enabled_skill(
        registry=build_document_skill_registry(),
        installations=build_document_skill_installations(app_id, subject_id),
        app_id=app_id,
        subject_id=subject_id,
        skill_id=skill_id,
    )


def resolve_skill_for_request(
    intake: SkillRequestIntake,
    *,
    app_id: str = DEFAULT_SKILL_APP_ID,
    subject_id: str = DEFAULT_SKILL_SUBJECT_ID,
) -> ReusableSkillPackage:
    """Resolve the Skill that serves a free-form request intake."""

    if not isinstance(intake, SkillRequestIntake):
        raise ContractError("intake must be SkillRequestIntake")
    return resolve_document_skill(
        DOCUMENT_SKILL_BY_DOC_TYPE[intake.resolved_doc_type].skill_id,
        app_id=app_id,
        subject_id=subject_id,
    )


def document_skill_catalogue(
    *,
    app_id: str = DEFAULT_SKILL_APP_ID,
    subject_id: str = DEFAULT_SKILL_SUBJECT_ID,
) -> tuple[dict[str, Any], ...]:
    """Return the catalogue rows — the registration evidence surface.

    Each row merges the Core public projection (``RegisteredSkill.to_public_dict``)
    with the kagent-side document binding, and states plainly that Engine
    execution is not yet wired (``ENGINE_RUNTIME_READY``).
    """

    registry = build_document_skill_registry()
    installations = build_document_skill_installations(app_id, subject_id)
    doc_type_by_skill_id = {
        package.skill_id: doc_type for doc_type, package in DOCUMENT_SKILL_BY_DOC_TYPE.items()
    }
    rows: list[dict[str, Any]] = []
    for entry in registry.entries:
        package = entry.package
        row = dict(entry.to_public_dict())
        row.update(
            {
                "fingerprint": entry.fingerprint,
                "description": package.description,
                "input_contract_ref": package.input_contract_ref,
                "output_contract_ref": package.output_contract_ref,
                "doc_type": doc_type_by_skill_id.get(package.skill_id),
                "execution_budget": {
                    "max_steps": package.execution_budget.max_steps,
                    "max_tool_calls": package.execution_budget.max_tool_calls,
                    "max_wall_seconds": package.execution_budget.max_wall_seconds,
                },
                "approval_hooks": [hook.value for hook in package.approval_hooks],
                "installed": True,
                "enabled": installations.get(
                    app_id=app_id, subject_id=subject_id, skill_id=package.skill_id
                ).enabled,
                "engine_runtime_ready": ENGINE_RUNTIME_READY,
                "engine_runtime_dependencies": list(ENGINE_RUNTIME_DEPENDENCIES),
            }
        )
        rows.append(row)
    return tuple(rows)


def run_skill_catalogue_command(
    *,
    action: str | None = None,
    skill_id: str | None = None,
    request_text: str | None = None,
    doc_type: str | None = None,
) -> int:
    """Print the registered-Skill catalogue or a free-form intake resolution.

    Read-only and provider-free: it never constructs an Engine request, so it
    cannot trigger a model call. Used by the ``kagent skill`` CLI subcommand.
    """

    if action == "show":
        if not skill_id:
            print("KAGENT_SKILL: skill_id가 필요합니다.", file=sys.stderr)
            return 2
        try:
            package = resolve_document_skill(skill_id)
        except (ContractError, ValueError) as exc:
            print(f"KAGENT_SKILL: {redact_secrets(str(exc))}", file=sys.stderr)
            return 2
        print(f"skill_id={package.skill_id}")
        print(f"publisher_id={package.publisher_id}")
        print(f"input_contract_ref={package.input_contract_ref}")
        print(f"output_contract_ref={package.output_contract_ref}")
        print(f"required_capabilities={','.join(package.required_capabilities) or '-'}")
        print(f"approval_hooks={','.join(hook.value for hook in package.approval_hooks) or '-'}")
        print(f"max_steps={package.execution_budget.max_steps}")
        print(f"engine_runtime_ready={ENGINE_RUNTIME_READY}")
        print(package.instruction.strip())
        return 0

    if action == "intake":
        try:
            intake = SkillRequestIntake(request_text=request_text or "", doc_type=doc_type)
            package = resolve_skill_for_request(intake)
        except (ContractError, ValueError) as exc:
            print(f"KAGENT_SKILL: {redact_secrets(str(exc))}", file=sys.stderr)
            return 2
        payload = intake.to_input_payload()
        print(f"skill_id={package.skill_id}")
        print(f"doc_type={payload['doc_type']}")
        print(f"contract={payload['contract']}")
        print(f"request_chars={len(payload['request_text'])}")
        print(f"attachments={len(payload['attachments'])}")
        print(f"engine_runtime_ready={ENGINE_RUNTIME_READY}")
        print(f"engine_runtime_dependencies={','.join(ENGINE_RUNTIME_DEPENDENCIES)}")
        print("요청 텍스트가 스킬 입력 계약으로 정규화되었습니다 (엔진 호출 없음).")
        return 0

    for row in document_skill_catalogue():
        print(
            f"{row['skill_id']} · doc_type={row['doc_type']} · "
            f"enabled={row['enabled']} · capabilities={','.join(row['required_capabilities'])} · "
            f"engine_runtime_ready={row['engine_runtime_ready']}"
        )
    print(
        f"등록 스킬 {len(DOCUMENT_SKILL_PACKAGES)}건 · "
        f"입력 계약={FREE_FORM_REQUEST_INPUT_CONTRACT_REF} · "
        f"엔진 런타임 대기={','.join(ENGINE_RUNTIME_DEPENDENCIES)}"
    )
    return 0


__all__ = [
    "CUSTOMER_QUOTE_DOC_TYPE",
    "CUSTOMER_QUOTE_OUTPUT_CONTRACT_REF",
    "CUSTOMER_QUOTE_SKILL",
    "CUSTOMER_QUOTE_SKILL_ID",
    "DEFAULT_SKILL_APP_ID",
    "DEFAULT_SKILL_SUBJECT_ID",
    "DOCUMENT_DRAFT_CAPABILITY",
    "DOCUMENT_SKILL_BY_DOC_TYPE",
    "DOCUMENT_SKILL_PACKAGES",
    "ENGINE_RUNTIME_BLOCKER_CODE",
    "ENGINE_RUNTIME_DEPENDENCIES",
    "ENGINE_RUNTIME_READY",
    "FREE_FORM_REQUEST_INPUT_CONTRACT_REF",
    "MAX_FREEFORM_ATTACHMENTS",
    "MAX_FREEFORM_REQUEST_CHARS",
    "PURCHASE_ORDER_DOC_TYPE",
    "PURCHASE_ORDER_OUTPUT_CONTRACT_REF",
    "PURCHASE_ORDER_SKILL",
    "PURCHASE_ORDER_SKILL_ID",
    "SKILL_PUBLISHER_ID",
    "SkillRequestIntake",
    "build_document_skill_installations",
    "build_document_skill_registry",
    "document_skill_catalogue",
    "resolve_document_skill",
    "resolve_request_doc_type",
    "resolve_skill_for_request",
    "run_skill_catalogue_command",
]
