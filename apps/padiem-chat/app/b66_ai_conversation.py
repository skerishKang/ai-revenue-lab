"""B66 #4466/#4412: server-owned general/quote conversation state machine.

The registered model interprets meaning and context, but the **server** owns
every state transition, every quote-fact validation and every WRITE boundary.
The model never receives calculation authority, quote-store authority or CGI
authority, and the browser never classifies intent itself.

Rules enforced here:

- The word 견적 alone never switches to quote authoring. The model's classified
  intent plus the current server state decides the transition, and the server
  may refuse a transition the state does not allow.
- A general conversation is never auto-saved as a quote draft. A draft is only
  produced by the existing client QuoteCore paths after an explicit customer
  approval action on the review screen.
- No model intent ever grants quote WRITE authority (save / overwrite / PDF).
- QuoteCore remains the only calculation authority: every totals/supply/VAT key
  is rejected on arrival, so a model can never smuggle in a computed amount.
- Missing required fields are confirmed with the customer one at a time; already
  known facts are preserved across turns.
"""
from __future__ import annotations

import json
import re
from typing import Any

SCHEMA = "b66.ai-conversation.v1"

MODE_GENERAL = "general"
MODE_QUOTE = "quote_authoring"
MODES = frozenset({MODE_GENERAL, MODE_QUOTE})

# Model-classified intent. The server, not the model, decides what an intent
# is allowed to do in the current state.
INTENTS = frozenset(
    {"general", "quote_explain", "quote_create", "quote_modify", "exit_quote", "clarify", "confirm"}
)

METHOD_FLEXIBLE = "flexible"
METHOD_GUIDED = "guided"
METHODS = frozenset({METHOD_FLEXIBLE, METHOD_GUIDED})

ACTION_APPROVE_DRAFT = "approve_draft"
ACTION_START_NEW = "start_new"

ACTIONS = frozenset({"message", "choose_method", "confirm", "cancel_staged", ACTION_APPROVE_DRAFT, ACTION_START_NEW})

TAX_MODES = frozenset({"EXCLUSIVE", "INCLUSIVE", "EXEMPT"})

# Bounded conversation limits. Message/reply size is provider-owned; this module
# bounds the *persisted* state so one turn can never grow the slot without end.
MAX_MESSAGE_CHARS = 2_000
MAX_REPLY_CHARS = 2_000
MAX_HISTORY_TURNS = 8
MAX_STATE_BYTES = 32_768
MAX_ITEMS = 20
MAX_ITEM_NAME_CHARS = 240
MAX_TEXT_CHARS = 240
MAX_MEMO_CHARS = 1_000
MAX_PROMPT_CHARS = 4_000

_FACTS_KEYS = frozenset({"recipient", "items", "taxMode", "memo", "projectName"})
_RECIPIENT_KEYS = frozenset({"company", "person", "address", "email"})
_ITEM_KEYS = frozenset({"name", "qty", "unitPrice", "unit"})

# QuoteCore owns every computed amount. A model reply or a stored fact may never
# carry one of these keys.
_FORBIDDEN_TOTAL_KEYS = frozenset(
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
        "saved_skill_id",
        "savedSkillId",
    }
)

_NUMERIC_TEXT_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(\{.*\})\s*```$", re.IGNORECASE | re.DOTALL)
_JSON_FENCE_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
# A wrapper sentence around the payload may not contain any structural marker:
# a brace/bracket/fence means a second payload or a stray fragment.
_STRUCTURAL_MARKERS = ("{", "}", "[", "]", "```")


class B66ConversationError(ValueError):
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


class ConversationRevisionConflict(B66ConversationError):
    """A concurrent writer already committed a newer revision of this slot.

    Raised only by the store's revision compare-and-swap, and only when the
    database positively reports that zero rows were affected. It is a bounded
    ``revision_conflict`` outcome for the client, never a lost update: the
    first committed state is the durable one.
    """

    def __init__(self) -> None:
        super().__init__("revision_conflict")


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _bounded_text(value: Any, *, limit: int, path: str) -> str:
    if not isinstance(value, str):
        raise B66ConversationError(
            "invalid_text", path=path, observed_type=_json_type_name(value)
        )
    if len(value) > limit:
        raise B66ConversationError("text_too_long", path=path, observed_type="string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise B66ConversationError(
            "invalid_text", path=path, observed_type="string"
        ) from exc
    return value


def _bounded_number(value: Any, *, path: str) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise B66ConversationError(
            "invalid_number", path=path, observed_type=_json_type_name(value)
        )
    if value != value or value in (float("inf"), float("-inf")):
        raise B66ConversationError(
            "invalid_number", path=path, observed_type="number"
        )
    if value < 0 or value > 10**12:
        raise B66ConversationError("number_out_of_range", path=path, observed_type="number")
    return value


def _reject_forbidden_keys(value: Any, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            for forbidden in _FORBIDDEN_TOTAL_KEYS:
                if normalized == forbidden.replace("_", "").replace("-", "").lower():
                    raise B66ConversationError(
                        "forbidden_total_key", path=f"{path}.{key}", observed_type="object"
                    )
            _reject_forbidden_keys(child, path=f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, path=f"{path}[{index}]")


def _normalize_recipient(value: Any, *, path: str) -> dict:
    if not isinstance(value, dict) or set(value) - _RECIPIENT_KEYS:
        raise B66ConversationError(
            "invalid_recipient", path=path, observed_type=_json_type_name(value)
        )
    return {
        key: _bounded_text(value.get(key, ""), limit=MAX_TEXT_CHARS, path=f"{path}.{key}")
        for key in sorted(_RECIPIENT_KEYS)
    }


def _normalize_item(value: Any, *, path: str) -> dict:
    if not isinstance(value, dict) or set(value) - _ITEM_KEYS:
        raise B66ConversationError(
            "invalid_item", path=path, observed_type=_json_type_name(value)
        )
    qty = _bounded_number(value.get("qty"), path=f"{path}.qty")
    unit_price = _bounded_number(value.get("unitPrice"), path=f"{path}.unitPrice")
    if isinstance(qty, (int, float)) and qty == 0:
        qty = None
    if isinstance(unit_price, (int, float)) and unit_price == 0:
        unit_price = None
    return {
        "name": _bounded_text(value.get("name", ""), limit=MAX_ITEM_NAME_CHARS, path=f"{path}.name"),
        "qty": qty,
        "unitPrice": unit_price,
        "unit": _bounded_text(value.get("unit", ""), limit=40, path=f"{path}.unit"),
    }


def _normalize_items(value: Any, *, path: str) -> list:
    if not isinstance(value, list):
        raise B66ConversationError(
            "invalid_items", path=path, observed_type=_json_type_name(value)
        )
    if len(value) > MAX_ITEMS:
        raise B66ConversationError("too_many_items", path=path, observed_type="array")
    return [
        _normalize_item(item, path=f"{path}[{index}]") for index, item in enumerate(value)
    ]


def normalize_facts(value: Any) -> dict:
    """Return the full facts object with every key present.

    Absent/empty values normalize to their empty form so stored facts always
    have one canonical shape regardless of which fields a turn carried.
    """
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise B66ConversationError(
            "invalid_facts", observed_type=_json_type_name(value)
        )
    if set(value) - _FACTS_KEYS:
        raise B66ConversationError("unexpected_facts_fields", observed_type="object")
    _reject_forbidden_keys(value, path="facts")
    tax_mode = value.get("taxMode") or ""
    if tax_mode not in TAX_MODES:
        tax_mode = ""
    return {
        "recipient": _normalize_recipient(value.get("recipient") or {}, path="facts.recipient"),
        "items": _normalize_items(value.get("items") or [], path="facts.items"),
        "taxMode": tax_mode,
        "memo": _bounded_text(value.get("memo") or "", limit=MAX_MEMO_CHARS, path="facts.memo"),
        "projectName": _bounded_text(
            value.get("projectName") or "", limit=MAX_TEXT_CHARS, path="facts.projectName"
        ),
    }


def normalize_facts_delta(value: Any) -> dict:
    """Validate a model-proposed facts delta, keeping only present keys.

    A delta only carries values the model claims the customer newly stated.
    The server merges it; it never replaces already-verified facts wholesale.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise B66ConversationError(
            "invalid_facts", observed_type=_json_type_name(value)
        )
    if set(value) - _FACTS_KEYS:
        raise B66ConversationError("unexpected_facts_fields", observed_type="object")
    _reject_forbidden_keys(value, path="facts")
    delta: dict[str, Any] = {}
    if "recipient" in value:
        delta["recipient"] = _normalize_recipient(value.get("recipient") or {}, path="facts.recipient")
    if "items" in value:
        delta["items"] = _normalize_items(value.get("items") or [], path="facts.items")
    if "taxMode" in value:
        tax_mode = value["taxMode"]
        if isinstance(tax_mode, str) and tax_mode == "":
            # Exactly empty means *not provided*. The model routinely emits a
            # placeholder for a tax mode the customer never stated. Accepting it
            # as absent leaves a known tax mode untouched and stages nothing;
            # it never clears or changes an existing value. Every other value
            # is still validated: a non-string type, an unknown non-empty
            # string, or a mode outside the closed set is refused.
            pass
        elif not isinstance(tax_mode, str) or tax_mode not in TAX_MODES:
            raise B66ConversationError("invalid_tax_mode", path="facts.taxMode", observed_type=_json_type_name(tax_mode))
        else:
            delta["taxMode"] = tax_mode
    if "memo" in value:
        delta["memo"] = _bounded_text(value.get("memo") or "", limit=MAX_MEMO_CHARS, path="facts.memo")
    if "projectName" in value:
        delta["projectName"] = _bounded_text(
            value.get("projectName") or "", limit=MAX_TEXT_CHARS, path="facts.projectName"
        )
    return delta


def merge_facts(current: Any, delta: Any) -> dict:
    """Server-owned merge: a delta updates only the facts it actually carries.

    Recipient fields and item rows are merged per field, so an earlier answer is
    never erased by a later turn that only mentions one value.
    """
    base = normalize_facts(current)
    patch = normalize_facts_delta(delta)
    if "recipient" in patch:
        for key, value in patch["recipient"].items():
            if value:
                base["recipient"][key] = value
    if "items" in patch:
        merged: list[dict] = []
        for row in base["items"]:
            merged.append(dict(row))
        for row in patch["items"]:
            name = row["name"].strip()
            if not name:
                # A nameless row carries no identity; only fill a bare row.
                if merged and not merged[-1]["name"]:
                    target = merged[-1]
                    target["qty"] = row["qty"] if row["qty"] is not None else target["qty"]
                    target["unitPrice"] = (
                        row["unitPrice"] if row["unitPrice"] is not None else target["unitPrice"]
                    )
                    target["unit"] = row["unit"] or target["unit"]
                continue
            existing = next((item for item in merged if item["name"] == name), None)
            if existing is None:
                merged.append(dict(row))
            else:
                if row["qty"] is not None:
                    existing["qty"] = row["qty"]
                if row["unitPrice"] is not None:
                    existing["unitPrice"] = row["unitPrice"]
                if row["unit"]:
                    existing["unit"] = row["unit"]
        base["items"] = merged[:MAX_ITEMS]
    if "taxMode" in patch:
        base["taxMode"] = patch["taxMode"]
    if patch.get("memo"):
        base["memo"] = patch["memo"]
    if patch.get("projectName"):
        base["projectName"] = patch["projectName"]
    return base


_MISSING_QUESTIONS = {
    "recipient": "받으실 거래처(회사명) 또는 담당자명을 알려 주세요.",
    "items": "견적에 넣을 품목을 알려 주세요.",
}


def missing_fields(facts: Any) -> list[str]:
    """Ordered required-missing tokens. Deterministic server derivation.

    taxMode is deliberately not required: an unknown tax mode is carried as
    taxUnknown through the existing review path instead of blocking the
    customer forever.
    """
    data = normalize_facts(facts)
    missing: list[str] = []
    recipient = data["recipient"]
    if not (recipient["company"].strip() or recipient["person"].strip()):
        missing.append("recipient")
    items = data["items"]
    if not items:
        missing.append("items")
    else:
        for index, item in enumerate(items):
            if not item["name"].strip():
                missing.append(f"items[{index}].name")
            if item["qty"] is None:
                missing.append(f"items[{index}].qty")
            if item["unitPrice"] is None:
                missing.append(f"items[{index}].unitPrice")
    return missing


def next_question(missing: Any) -> str | None:
    """One short server-authored question for the first genuinely missing field."""
    for token in missing or ():
        if token in _MISSING_QUESTIONS:
            return _MISSING_QUESTIONS[token]
        if token.endswith(".name"):
            return "품목명을 알려 주세요."
        if token.endswith(".qty"):
            return "수량은 몇인가요?"
        if token.endswith(".unitPrice"):
            return "단가는 얼마인가요?"
    return None


def empty_state() -> dict:
    return {
        "schema": SCHEMA,
        "mode": MODE_GENERAL,
        "method": None,
        "awaiting_method": False,
        "staged": False,
        "approval_required": False,
        "facts": normalize_facts(None),
        "staged_facts": None,
        "missing": [],
        "last_user_message": "",
        "last_answer": "",
        "answer_origin": "server_state",
        "history": [],
        "revision": 0,
    }


def normalize_conversation_state(payload: Any) -> dict:
    """Validate and bound a persisted conversation state (never trust the row)."""
    state = empty_state()
    if payload is None:
        return state
    if not isinstance(payload, dict):
        raise B66ConversationError(
            "invalid_state", observed_type=_json_type_name(payload)
        )
    if payload.get("schema") != SCHEMA:
        raise B66ConversationError("unsupported_schema")
    mode = payload.get("mode")
    if mode not in MODES:
        raise B66ConversationError("invalid_mode", path="mode", observed_type=_json_type_name(mode))
    state["mode"] = mode
    method = payload.get("method")
    if method is not None and method not in METHODS:
        raise B66ConversationError(
            "invalid_method", path="method", observed_type=_json_type_name(method)
        )
    state["method"] = method
    for flag in ("awaiting_method", "staged", "approval_required"):
        value = payload.get(flag)
        if not isinstance(value, bool):
            raise B66ConversationError("invalid_flag", path=flag, observed_type=_json_type_name(value))
        state[flag] = value
    state["facts"] = normalize_facts(payload.get("facts"))
    staged = payload.get("staged_facts")
    # A staged change is a *delta*: only the keys the change proposes. It is
    # never a canonical full facts object, so it is validated with the delta
    # contract (an empty-string taxMode would be an absent value, not a fact).
    state["staged_facts"] = None if staged is None else normalize_facts_delta(staged)
    missing = payload.get("missing")
    if not isinstance(missing, list) or not all(isinstance(token, str) for token in missing):
        raise B66ConversationError("invalid_missing", path="missing", observed_type=_json_type_name(missing))
    state["missing"] = [token[:64] for token in missing][:16]
    state["last_user_message"] = _bounded_text(
        payload.get("last_user_message") or "", limit=MAX_MESSAGE_CHARS, path="last_user_message"
    )
    state["last_answer"] = _bounded_text(
        payload.get("last_answer") or "", limit=MAX_REPLY_CHARS, path="last_answer"
    )
    origin = payload.get("answer_origin")
    if origin not in {"server_state", "registered_model_completion"}:
        raise B66ConversationError(
            "invalid_answer_origin", path="answer_origin", observed_type=_json_type_name(origin)
        )
    state["answer_origin"] = origin
    history = payload.get("history")
    if not isinstance(history, list):
        raise B66ConversationError(
            "invalid_history", path="history", observed_type=_json_type_name(history)
        )
    bounded_history = []
    for item in history[-MAX_HISTORY_TURNS:]:
        if (
            not isinstance(item, dict)
            or set(item) != {"role", "content"}
            or item.get("role") not in {"user", "assistant"}
        ):
            raise B66ConversationError("invalid_history_item", path="history", observed_type="object")
        bounded_history.append(
            {
                "role": item["role"],
                "content": _bounded_text(
                    item.get("content") or "", limit=MAX_REPLY_CHARS, path="history.content"
                ),
            }
        )
    state["history"] = bounded_history
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise B66ConversationError(
            "invalid_revision", path="revision", observed_type=_json_type_name(revision)
        )
    state["revision"] = min(revision, 10_000_000)
    return state


def parse_model_output(text: Any) -> tuple[str, str, dict]:
    """Strictly parse the model's bounded JSON reply into (reply, intent, delta).

    Fail-closed: anything that is not exactly one payload with the contract
    keys raises, and the caller keeps the previous state untouched. The model
    is never asked to compute totals, so any attempt is rejected, not parsed.
    """
    if not isinstance(text, str) or not text.strip():
        raise B66ConversationError("empty_model_output")
    clean = text.strip()
    fenced = _JSON_FENCE_RE.match(clean)
    if fenced:
        clean = fenced.group(1).strip()
    else:
        block = _JSON_FENCE_BLOCK_RE.search(clean)
        if block:
            # Prose may wrap a single fenced payload, but a second payload or
            # a stray fragment next to it means the output is ambiguous.
            remainder = clean.replace(block.group(0), "", 1)
            if any(marker in remainder for marker in _STRUCTURAL_MARKERS):
                raise B66ConversationError("ambiguous_model_output")
            clean = block.group(1).strip()
        # No fence: the whole output must itself be exactly one JSON object.
    try:
        payload = json.loads(clean)
    except (json.JSONDecodeError, ValueError) as exc:
        raise B66ConversationError("invalid_model_json") from exc
    if not isinstance(payload, dict) or set(payload) - {"reply", "intent", "facts"}:
        raise B66ConversationError(
            "unexpected_model_keys", observed_type=_json_type_name(payload)
        )
    reply = payload.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise B66ConversationError(
            "invalid_reply", path="reply", observed_type=_json_type_name(reply)
        )
    reply = reply.strip()
    if len(reply) > MAX_REPLY_CHARS:
        raise B66ConversationError("reply_too_long", path="reply", observed_type="string")
    intent = payload.get("intent")
    if intent not in INTENTS:
        raise B66ConversationError(
            "invalid_intent", path="intent", observed_type=_json_type_name(intent)
        )
    delta = normalize_facts_delta(payload.get("facts"))
    return reply, intent, delta


def conversation_prompt(state: dict) -> str:
    """The model's system instruction for one turn, given the server state."""
    data = normalize_conversation_state(state)
    known = data["facts"]
    recipient = known["recipient"]
    item_lines = []
    for item in known["items"]:
        qty = "" if item["qty"] is None else str(item["qty"])
        price = "" if item["unitPrice"] is None else str(item["unitPrice"])
        item_lines.append(
            f"품목:{item['name'] or '(미입력)'} 수량:{qty or '(미입력)'} 단가:{price or '(미입력)'}"
        )
    history_lines = [
        f"{'고객' if turn['role'] == 'user' else 'AI'}: {turn['content']}"
        for turn in data["history"][-6:]
    ]
    prompt = (
        "당신은 B66 견적 상담 AI입니다. 한국어로만 답변하세요.\n"
        "출력은 JSON 한 개만 허용합니다: {\"reply\": string, \"intent\": string, \"facts\": object|null}\n"
        "- reply: 고객에게 보여줄 자연스러운 답변(2000자 이내). 답변 본문만.\n"
        "- intent는 다음 중 정확히 하나입니다:\n"
        "  general: 일상 대화·일반 정보 질문\n"
        "  quote_explain: 견적서 개념·절차·방법 설명 질문(작성 요청이 아님)\n"
        "  quote_create: 명확한 견적 작성 요청\n"
        "  quote_modify: 진행 중 견적의 수정 요청\n"
        "  exit_quote: 견적 주제를 끝내고 다른 이야기를 하자는 요청\n"
        "  clarify: 의도가 불명확할 때 고객에게 짧게 확인\n"
        "  confirm: 서버의 직전 확인 질문에 대한 긍정 답변\n"
        "- facts: 이번 고객 메시지에서 새로 알게 된 견적 정보만 담습니다. "
        "recipient{company,person}, items[{name,qty,unitPrice,unit}], taxMode, memo, projectName. "
        "이미 알고 있는 값은 반복하지 마세요. 합계·공급가액·부가세 등 계산값은 절대 넣지 마세요.\n"
        "- 이미 알고 있는 정보는 다시 묻지 마세요. 부족한 정보는 reply에서 한 가지만 짧게 확인하세요.\n"
        "- 당신은 견적을 저장·발급·덮어쓰기할 수 없습니다. 저장이나 PDF 안내는 하지 마세요.\n"
        f"현재 서버 상태: mode={data['mode']}, authoring_method={data['method'] or '없음'}, "
        f"awaiting_method={str(data['awaiting_method']).lower()}, staged={str(data['staged']).lower()}\n"
        "알려진 견적 정보: "
        f"거래처:{recipient['company'] or '(미입력)'} / 담당자:{recipient['person'] or '(미입력)'}; "
        + ("; ".join(item_lines) if item_lines else "품목 없음")
        + f"; taxMode:{known['taxMode'] or '(미입력)'}\n"
        f"아직 필요한 항목: {', '.join(data['missing']) if data['missing'] else '없음'}\n"
        + ("최근 대화:\n" + "\n".join(history_lines) if history_lines else "")
    )
    return prompt[:MAX_PROMPT_CHARS]


def delta_overwrites_known_facts(facts: Any, delta: Any) -> bool:
    """True when applying the delta would replace an already-known value.

    Collecting a *new* value is normal authoring. Replacing a value the customer
    already stated is a modification, and the model has no authority to make one:
    it must go through staging and the customer's explicit confirm action. This
    also stops a model from claiming ``confirm``/``quote_create`` and supplying
    the changed value in the same reply.
    """
    known = normalize_facts(facts)
    patch = normalize_facts_delta(delta)
    for key, value in (patch.get("recipient") or {}).items():
        if value and known["recipient"].get(key):
            return True
    for row in patch.get("items") or ():
        name = row["name"].strip()
        if not name:
            continue
        existing = next((item for item in known["items"] if item["name"] == name), None)
        if existing is None:
            continue
        for field in ("qty", "unitPrice"):
            if row[field] is not None and existing[field] is not None and row[field] != existing[field]:
                return True
        if row["unit"] and existing["unit"] and row["unit"] != existing["unit"]:
            return True
    for key in ("taxMode", "memo", "projectName"):
        if key in patch and patch[key] and known[key] and patch[key] != known[key]:
            return True
    return False


def apply_message_transition(state: dict, reply: str, intent: str, delta: dict) -> dict:
    """Server-authoritative transition for one answered message turn.

    The model proposes (reply, intent, delta); this function alone decides
    which transitions are legal from the current state. Quote facts may only be
    collected or modified inside the **server-owned quote-authoring scope**
    (``mode == MODE_QUOTE``), which the server itself opens and closes. Outside
    that scope a model reply mutates no quote fact at all — whichever intent
    label the model chose — so facts retained after ``exit_quote`` (or after a
    customer resumes months later) can only ever change through staging and the
    customer's explicit confirm action. The returned state carries a private
    ``_mode_changed`` marker for the response.
    """
    data = normalize_conversation_state(state)
    # Validate the proposal before anything reads it, so a delta that carries no
    # real change (e.g. only a placeholder tax mode) cannot stage or merge an
    # empty modification the customer would then have to confirm.
    delta = normalize_facts_delta(delta)
    staging = False
    if data["mode"] == MODE_QUOTE:
        # Authoring scope: the customer is actively building this quotation.
        if delta and (
            intent == "quote_modify" or delta_overwrites_known_facts(data["facts"], delta)
        ):
            # A modification is only staged. It is applied solely by an explicit
            # customer confirm action, never by a model intent — so the current
            # facts stay exactly as they were until that confirmation. A reply
            # that rewrites an already-known value is a modification no matter
            # which intent label the model chose (including a claimed
            # ``confirm``).
            staging = True
        elif delta:
            data["facts"] = merge_facts(data["facts"], delta)
    else:
        # General scope: no general/explain/clarify/confirm/quote_modify reply
        # has fact authority, and neither does a re-entering quote_create turn
        # for anything the customer already stated. The one collection that is
        # legitimate is an explicit authoring request that this very turn opens
        # authoring on, and only for genuinely new values.
        opens_authoring = intent == "quote_create"
        if (
            opens_authoring
            and delta
            and not delta_overwrites_known_facts(data["facts"], delta)
        ):
            data["facts"] = merge_facts(data["facts"], delta)
        # Anything else the model proposed has no authority here and is dropped
        # rather than merged: an unselected method and a reply that stands on
        # its own are the only outcomes of this turn.
        delta = {}
    mode_changed = False

    if data["mode"] == MODE_GENERAL:
        if intent == "quote_create":
            # Only an explicit authoring request opens authoring. The word 견적
            # alone (quote_explain / general) never does.
            data["mode"] = MODE_QUOTE
            # A complete one-sentence request does not need a redundant choice.
            complete_request = not missing_fields(data["facts"])
            if complete_request and data["method"] is None:
                data["method"] = METHOD_FLEXIBLE
            data["awaiting_method"] = data["method"] is None
            data["approval_required"] = False
            mode_changed = True
        # quote_modify without an active authoring slot stays general: there is
        # no in-conversation target yet, so the model's clarifying reply stands.
    else:  # quote_authoring
        if intent == "exit_quote":
            data["mode"] = MODE_GENERAL
            data["awaiting_method"] = False
            data["approval_required"] = False
            mode_changed = True
            # Facts are kept for resume; the customer never loses collected data.
        elif staging:
            data["staged"] = True
            # Keep the proposed change as a validated delta. Expanding it into a
            # canonical full facts object here would re-validate it as a delta at
            # confirm time and reject its own empty placeholders.
            data["staged_facts"] = normalize_facts_delta(delta)
            data["approval_required"] = True
        # quote_create keeps authoring; general/clarify/confirm stay in authoring.

    data["missing"] = missing_fields(data["facts"])
    if data["mode"] == MODE_QUOTE and data["staged"]:
        data["approval_required"] = True
    elif data["mode"] == MODE_QUOTE and data["missing"]:
        data["approval_required"] = False
    elif data["mode"] == MODE_QUOTE and data["method"] is not None and not data["missing"]:
        data["approval_required"] = True
    else:
        data["approval_required"] = False
    data["last_answer"] = reply
    data["answer_origin"] = "registered_model_completion"
    data["_mode_changed"] = mode_changed
    return data


def choose_method_transition(state: dict, method: str) -> dict:
    """Customer's explicit method choice. Server state only; no model call."""
    data = normalize_conversation_state(state)
    if data["mode"] != MODE_QUOTE:
        raise B66ConversationError("not_in_quote_mode")
    if method not in METHODS:
        raise B66ConversationError("invalid_method", path="method", observed_type="string")
    data["method"] = method
    data["awaiting_method"] = False
    data["missing"] = missing_fields(data["facts"])
    data["approval_required"] = bool(
        data["mode"] == MODE_QUOTE and not data["missing"] and not data["staged"]
    )
    return data


def confirm_transition(state: dict) -> dict:
    """Apply a staged modification only after the customer explicitly confirms.

    Confirmation is a customer action, never a model intent, so no model
    classification can modify collected facts by itself.
    """
    data = normalize_conversation_state(state)
    if not data["staged"]:
        raise B66ConversationError("no_staged_change")
    if data["staged_facts"]:
        data["facts"] = merge_facts(data["facts"], data["staged_facts"])
    data["staged"] = False
    data["staged_facts"] = None
    data["missing"] = missing_fields(data["facts"])
    data["approval_required"] = bool(data["mode"] == MODE_QUOTE and not data["missing"])
    return data


def cancel_staged_transition(state: dict) -> dict:
    data = normalize_conversation_state(state)
    if not data["staged"]:
        raise B66ConversationError("no_staged_change")
    data["staged"] = False
    data["staged_facts"] = None
    data["approval_required"] = bool(data["mode"] == MODE_QUOTE and not data["missing"])
    return data


QUOTE_DRAFT_SOURCE = "b66.ai-conversation"


def quote_draft_from_facts(facts: Any) -> dict:
    """The canonical QuoteCore draft input for the collected conversation facts.

    Only facts the customer actually stated are emitted, in the same shape the
    existing B66 quote interpreter projects. ``quoteNo``/``issueDate`` and every
    computed amount (supplyAmount, vatAmount, grandTotal, …) stay with the
    existing QuoteCore path: this function never derives a price, a subtotal or
    a total, and an absent quantity/price is omitted rather than defaulted.
    """
    data = normalize_facts(facts)
    items: list[dict[str, Any]] = []
    for item in data["items"]:
        row: dict[str, Any] = {"name": item["name"]}
        if item["unit"]:
            row["unit"] = item["unit"]
        if item["qty"] is not None:
            row["qty"] = item["qty"]
        if item["unitPrice"] is not None:
            row["unitPrice"] = item["unitPrice"]
        items.append(row)
    return {
        "sourceKind": QUOTE_DRAFT_SOURCE,
        "recipient": dict(data["recipient"]),
        "projectName": data["projectName"],
        "items": items,
        "detailGroups": [],
        "memo": data["memo"],
        "taxMode": data["taxMode"],
        "missing": missing_fields(data),
    }


def approve_draft_transition(state: dict) -> tuple[dict, dict]:
    """The customer's explicit approval is the only path to a quote draft.

    Approval is a customer action that carries its own request; a model intent
    can never reach it. It is refused while the authoring method is unselected,
    while a modification is still staged, or while a required field is missing —
    so no unconfirmed or partial content can reach QuoteCore. Nothing is saved,
    overwritten or issued here: the draft is returned for the existing QuoteCore
    path, which alone computes and persists the quotation.
    """
    data = normalize_conversation_state(state)
    if data["mode"] != MODE_QUOTE:
        raise B66ConversationError("not_in_quote_mode")
    if data["staged"]:
        raise B66ConversationError("staged_change_pending")
    if data["awaiting_method"] or data["method"] is None:
        raise B66ConversationError("method_not_selected")
    if missing_fields(data["facts"]):
        raise B66ConversationError("missing_quote_fields")
    draft = quote_draft_from_facts(data["facts"])
    # The conversation-level review step is done; saving/issuing the quotation
    # still requires the customer's explicit action on the review screen.
    data["approval_required"] = False
    return data, draft


SERVER_CONFIRM_ANSWER = (
    "수정 내용을 반영했습니다. 내용을 확인한 뒤 초안 만들기를 선택하면 됩니다."
)
SERVER_DRAFT_ANSWER = (
    "확인해 주신 내용으로 견적 초안을 만들었습니다. "
    "화면에서 초안을 확인한 뒤 저장하거나 PDF로 발급하세요."
)
SERVER_CANCEL_ANSWER = "수정 요청을 취소했습니다. 기존 내용을 그대로 유지합니다."
SERVER_METHOD_ANSWERS = {
    METHOD_FLEXIBLE: (
        "한 번에 설명하는 방식으로 진행할게요. 품목·수량·단가·거래처를 편하게 알려 주세요."
    ),
    METHOD_GUIDED: (
        "질문하며 작성하는 방식으로 진행할게요. 필요한 항목을 한 번에 하나씩 물어보겠습니다."
    ),
}


def state_summary(state: dict) -> dict:
    """Public projection: conversation facts and status, never a message log."""
    data = normalize_conversation_state(state)
    return {
        "mode": data["mode"],
        "method": data["method"],
        "awaiting_method": data["awaiting_method"],
        "staged": data["staged"],
        "approval_required": data["approval_required"],
        "facts": data["facts"],
        "missing": data["missing"],
        "next_question": next_question(data["missing"]),
        "revision": data["revision"],
        "answer_origin": data["answer_origin"],
    }


def append_history(state: dict, user_message: str, reply: str) -> dict:
    data = normalize_conversation_state(state)
    data["history"] = (
        data["history"]
        + [
            {"role": "user", "content": user_message[:MAX_MESSAGE_CHARS]},
            {"role": "assistant", "content": reply[:MAX_REPLY_CHARS]},
        ]
    )[-MAX_HISTORY_TURNS:]
    return data


def bump_revision(state: dict) -> dict:
    data = normalize_conversation_state(state)
    data["revision"] = min(data["revision"] + 1, 10_000_000)
    return data


def valid_revision(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 10_000_000
    )


__all__ = [
    "ACTION_APPROVE_DRAFT",
    "ACTION_START_NEW",
    "ACTIONS",
    "B66ConversationError",
    "ConversationRevisionConflict",
    "INTENTS",
    "MAX_HISTORY_TURNS",
    "MAX_MESSAGE_CHARS",
    "MAX_REPLY_CHARS",
    "MAX_STATE_BYTES",
    "METHOD_FLEXIBLE",
    "METHOD_GUIDED",
    "METHODS",
    "MODE_GENERAL",
    "MODE_QUOTE",
    "MODES",
    "QUOTE_DRAFT_SOURCE",
    "SCHEMA",
    "SERVER_CANCEL_ANSWER",
    "SERVER_CONFIRM_ANSWER",
    "SERVER_DRAFT_ANSWER",
    "SERVER_METHOD_ANSWERS",
    "append_history",
    "apply_message_transition",
    "approve_draft_transition",
    "bump_revision",
    "cancel_staged_transition",
    "choose_method_transition",
    "confirm_transition",
    "conversation_prompt",
    "delta_overwrites_known_facts",
    "empty_state",
    "merge_facts",
    "missing_fields",
    "next_question",
    "normalize_conversation_state",
    "normalize_facts",
    "normalize_facts_delta",
    "parse_model_output",
    "quote_draft_from_facts",
    "state_summary",
    "valid_revision",
]
