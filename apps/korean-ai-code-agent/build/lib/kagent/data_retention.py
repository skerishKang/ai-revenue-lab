from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sha(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value


class RetainedDataClass(str, Enum):
    INBOUND_MESSAGE_BODY = "inbound_message_body"
    SOURCE_DOCUMENT = "source_document"
    EXTRACTED_CANDIDATE = "extracted_candidate"
    BUSINESS_RECORD = "business_record"
    RENDERED_ARTIFACT = "rendered_artifact"
    PRODUCT_EVIDENCE_PROJECTION = "product_evidence_projection"
    PILOT_AGGREGATE = "pilot_aggregate"


class RetentionDisposition(str, Enum):
    KEEP = "keep"
    DELETE_DUE = "delete_due"
    LEGAL_HOLD = "legal_hold"


@dataclass(frozen=True, slots=True)
class RetentionRule:
    data_class: RetainedDataClass
    ttl_days: int

    def __post_init__(self) -> None:
        if not isinstance(self.data_class, RetainedDataClass):
            raise ContractError("data_class must be RetainedDataClass")
        if isinstance(self.ttl_days, bool) or not isinstance(self.ttl_days, int) or not 1 <= self.ttl_days <= 3650:
            raise ContractError("ttl_days must be between 1 and 3650")


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    policy_ref: str
    version: int
    rules: tuple[RetentionRule, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_ref", _ref(self.policy_ref, "policy_ref"))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ContractError("retention policy version must be positive")
        if not isinstance(self.rules, tuple) or not self.rules:
            raise ContractError("retention policy requires rules")
        classes = tuple(rule.data_class for rule in self.rules if isinstance(rule, RetentionRule))
        if len(classes) != len(self.rules):
            raise ContractError("rules must contain RetentionRule")
        if len(classes) != len(set(classes)):
            raise ContractError("retention policy data classes must be unique")
        if set(classes) != set(RetainedDataClass):
            raise ContractError("retention policy must define every retained data class")

    def ttl_for(self, data_class: RetainedDataClass) -> int:
        for rule in self.rules:
            if rule.data_class is data_class:
                return rule.ttl_days
        raise ContractError("retention policy is incomplete")


DEFAULT_RETENTION_POLICY = RetentionPolicy(
    policy_ref="b54_retention_m1",
    version=1,
    rules=(
        RetentionRule(RetainedDataClass.INBOUND_MESSAGE_BODY, 30),
        RetentionRule(RetainedDataClass.SOURCE_DOCUMENT, 90),
        RetentionRule(RetainedDataClass.EXTRACTED_CANDIDATE, 30),
        RetentionRule(RetainedDataClass.BUSINESS_RECORD, 365),
        RetentionRule(RetainedDataClass.RENDERED_ARTIFACT, 90),
        RetentionRule(RetainedDataClass.PRODUCT_EVIDENCE_PROJECTION, 365),
        RetentionRule(RetainedDataClass.PILOT_AGGREGATE, 730),
    ),
)


@dataclass(frozen=True, slots=True)
class RetainedRecordMetadata:
    record_ref: str
    workspace_id: str
    data_class: RetainedDataClass
    content_sha256: str
    created_at: datetime
    policy_ref: str
    policy_version: int
    legal_hold_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("record_ref", "workspace_id", "policy_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if not isinstance(self.data_class, RetainedDataClass):
            raise ContractError("data_class must be RetainedDataClass")
        object.__setattr__(self, "content_sha256", _sha(self.content_sha256, "content_sha256"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if isinstance(self.policy_version, bool) or not isinstance(self.policy_version, int) or self.policy_version < 1:
            raise ContractError("policy_version must be positive")
        if self.legal_hold_ref is not None:
            object.__setattr__(self, "legal_hold_ref", _ref(self.legal_hold_ref, "legal_hold_ref"))


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    record_ref: str
    disposition: RetentionDisposition
    delete_after: datetime
    legal_hold_ref: str | None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "record_ref": self.record_ref,
            "disposition": self.disposition.value,
            "delete_after": self.delete_after.isoformat().replace("+00:00", "Z"),
            "legal_hold_ref": self.legal_hold_ref,
            "model_set_retention": False,
        }


def evaluate_retention(*, record: RetainedRecordMetadata, policy: RetentionPolicy, now: datetime) -> RetentionDecision:
    if not isinstance(record, RetainedRecordMetadata) or not isinstance(policy, RetentionPolicy):
        raise ContractError("record and policy must be retention contracts")
    now = _aware(now, "now")
    if record.policy_ref != policy.policy_ref or record.policy_version != policy.version:
        raise ContractError("record retention policy reference/version mismatch")
    delete_after = record.created_at + timedelta(days=policy.ttl_for(record.data_class))
    if record.legal_hold_ref is not None:
        disposition = RetentionDisposition.LEGAL_HOLD
    elif now >= delete_after:
        disposition = RetentionDisposition.DELETE_DUE
    else:
        disposition = RetentionDisposition.KEEP
    return RetentionDecision(record.record_ref, disposition, delete_after, record.legal_hold_ref)


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    receipt_id: str
    record_ref: str
    workspace_id: str
    data_class: RetainedDataClass
    deleted_content_sha256: str
    policy_ref: str
    policy_version: int
    deleted_at: datetime
    deletion_authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("receipt_id", "record_ref", "workspace_id", "policy_ref", "deletion_authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "deleted_content_sha256", _sha(self.deleted_content_sha256, "deleted_content_sha256"))
        object.__setattr__(self, "deleted_at", _aware(self.deleted_at, "deleted_at"))
        if not isinstance(self.data_class, RetainedDataClass):
            raise ContractError("data_class must be RetainedDataClass")
        if isinstance(self.policy_version, bool) or not isinstance(self.policy_version, int) or self.policy_version < 1:
            raise ContractError("policy_version must be positive")

    @classmethod
    def attest(
        cls,
        *,
        record: RetainedRecordMetadata,
        decision: RetentionDecision,
        deleted_at: datetime,
        deletion_authority_ref: str,
        evidence_ref: str,
    ) -> "DeletionReceipt":
        deleted_at = _aware(deleted_at, "deleted_at")
        if decision.record_ref != record.record_ref or decision.disposition is not RetentionDisposition.DELETE_DUE:
            raise ContractError("deletion receipt requires exact DELETE_DUE decision")
        if record.legal_hold_ref is not None:
            raise ContractError("record under legal hold cannot receive deletion receipt")
        if deleted_at < decision.delete_after:
            raise ContractError("deletion receipt cannot predate retention deadline")
        digest = hashlib.sha256(
            json.dumps(
                {"record_ref": record.record_ref, "sha256": record.content_sha256, "deleted_at": deleted_at.isoformat()},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        return cls(
            receipt_id=f"deletion:{digest}",
            record_ref=record.record_ref,
            workspace_id=record.workspace_id,
            data_class=record.data_class,
            deleted_content_sha256=record.content_sha256,
            policy_ref=record.policy_ref,
            policy_version=record.policy_version,
            deleted_at=deleted_at,
            deletion_authority_ref=deletion_authority_ref,
            evidence_ref=evidence_ref,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-data-deletion-receipt.v1",
            "receipt_id": self.receipt_id,
            "record_ref": self.record_ref,
            "workspace_id": self.workspace_id,
            "data_class": self.data_class.value,
            "deleted_content_sha256": self.deleted_content_sha256,
            "policy_ref": self.policy_ref,
            "policy_version": self.policy_version,
            "deleted_at": self.deleted_at.isoformat().replace("+00:00", "Z"),
            "deletion_authority_ref": self.deletion_authority_ref,
            "evidence_ref": self.evidence_ref,
            "deleted_content_present": False,
        }


MODEL_DEFINED_RETENTION_SUPPORTED = False
REAL_STORAGE_DELETE_CONFIGURED = False
RAW_CREDENTIAL_RETENTION_CLASS_SUPPORTED = False
HIDDEN_REASONING_RETENTION_CLASS_SUPPORTED = False
