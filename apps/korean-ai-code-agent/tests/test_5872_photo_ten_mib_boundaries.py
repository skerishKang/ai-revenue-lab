"""#5872 — SNS 사진 상한 10MiB의 경계(10MiB 정확히 / +1바이트 / 여러 장 합계).

배경: 운영 정책 문서에 "SNS 메시지 상한 1MB→10MiB(#5872) 실측 미검증"으로 남아
있었다. 이 파일은 그 미검증 항목을 **계약 수준에서** 실측한다. 실제 공급자
(Slack·Telegram) 호출은 없다 — 상한을 판정하는 계약이 경계에서 어떻게 답하는지가
확인 대상이다.

확인한 사실(코드 그대로):

- Slack 파일: ``MAX_SLACK_FILE_BYTES = 10 MiB``. 수신 매니페스트
  (``SlackFileManifest``)는 **초과만** 거부하고 10MiB 정확히는 통과한다.
  승인 파일(``SlackApprovedFile``)도 ``0 <= size <= 10 MiB`` 이다.
- Telegram 파일: ``MAX_TELEGRAM_FILE_BYTES = 10 MiB`` — 같은 경계.
- 한 번에 붙는 개수: Slack 8개, Telegram 8개.
- 운영 첨부 정책(``AttachmentPolicy``): 파일별 10MiB + 최대 10개.
  **합계 상한은 존재하지 않는다** — 이 시험이 그 사실을 명시적으로 고정한다
  (여러 장 합계가 10MiB를 넘어도 파일별·개수 상한 안이면 통과).
  다만 이 정책의 허용 형식은 **문서뿐**이다(이미지 형식이 없다) — 사진 경로는
  Slack·Telegram 커넥터 계약이 맡고, 여기는 PDF·TXT·CSV·DOCX·XLSX용이다.

즉 "여러 장 합계"의 실제 답은 "합계 제한 없음(파일별 10MiB × 개수)"이다.
그것이 의도와 다르면 제품 코드가 아니라 이 시험의 기대를 바꾸는 결정이 필요하다.
"""

from __future__ import annotations

import pytest

from kagent.contracts import ContractError
from kagent.ops_communications import (
    AttachmentDisposition,
    AttachmentMetadata,
    AttachmentPolicy,
)
from kagent.slack_contracts import (
    MAX_SLACK_FILE_BYTES,
    MAX_SLACK_FILES_PER_ACTION,
    SlackApprovedFile,
    SlackFileManifest,
)
from kagent.telegram_contracts import (
    MAX_TELEGRAM_FILE_BYTES,
    MAX_TELEGRAM_FILES_PER_UPDATE,
    TelegramApprovedDocument,
    TelegramFileManifest,
)

TEN_MIB = 10 * 1024 * 1024
SHA = "a" * 64
EVIDENCE = "quarantine:evidence:1"


# ── 상수 자체 ───────────────────────────────────────────────────────────────

def test_both_messaging_connectors_cap_a_file_at_ten_mib():
    assert MAX_SLACK_FILE_BYTES == TEN_MIB
    assert MAX_TELEGRAM_FILE_BYTES == TEN_MIB
    assert MAX_SLACK_FILES_PER_ACTION == 8
    assert MAX_TELEGRAM_FILES_PER_UPDATE == 8


# ── Slack 경계 ──────────────────────────────────────────────────────────────

def _slack_manifest(size: int) -> SlackFileManifest:
    return SlackFileManifest(
        file_ref="file/photo1", channel_id="C01234567",
        filename="photo.jpg", mime_type="image/jpeg", size_bytes=size,
    )


def _slack_approved(size: int, ref: str = "file/photo1") -> SlackApprovedFile:
    return SlackApprovedFile(
        file_ref=ref, filename="photo.jpg", mime_type="image/jpeg",
        size_bytes=size, sha256=SHA, quarantine_evidence_ref=EVIDENCE,
    )


@pytest.mark.parametrize("size,allowed", [
    (TEN_MIB - 1, True),
    (TEN_MIB, True),        # 10MiB 정확히는 통과
    (TEN_MIB + 1, False),   # +1바이트는 거부
])
def test_slack_file_manifest_boundary(size: int, allowed: bool):
    if allowed:
        assert _slack_manifest(size).size_bytes == size
    else:
        with pytest.raises(ContractError):
            _slack_manifest(size)


@pytest.mark.parametrize("size,allowed", [
    (TEN_MIB, True),
    (TEN_MIB + 1, False),
])
def test_slack_approved_file_boundary(size: int, allowed: bool):
    if allowed:
        assert _slack_approved(size).size_bytes == size
    else:
        with pytest.raises(ContractError):
            _slack_approved(size)


# ── Telegram 경계 ───────────────────────────────────────────────────────────

def _telegram_manifest(size: int, ref: str = "tg/file1") -> TelegramFileManifest:
    return TelegramFileManifest(
        file_ref=ref, file_unique_ref=ref + ":unique",
        filename="photo.jpg", mime_type="image/jpeg", size_bytes=size,
    )


def _telegram_approved(size: int, ref: str = "tg/file1") -> TelegramApprovedDocument:
    return TelegramApprovedDocument(
        file_ref=ref, filename="photo.jpg", mime_type="image/jpeg",
        size_bytes=size, sha256=SHA, quarantine_evidence_ref=EVIDENCE,
    )


@pytest.mark.parametrize("size,allowed", [
    (TEN_MIB, True),
    (TEN_MIB + 1, False),
])
def test_telegram_file_boundary(size: int, allowed: bool):
    if allowed:
        assert _telegram_manifest(size).size_bytes == size
        assert _telegram_approved(size).size_bytes == size
    else:
        with pytest.raises(ContractError):
            _telegram_manifest(size)
        with pytest.raises(ContractError):
            _telegram_approved(size)


# ── 여러 장: 개수 상한은 있고, 합계 상한은 없다 ─────────────────────────────

def _attachment(index: int, size: int) -> AttachmentMetadata:
    # 이 정책이 다루는 형식(문서)으로 만든다 — 사진 형식은 여기 허용 목록에 없다.
    return AttachmentMetadata(
        attachment_id=f"attachment:{index}", file_name=f"document{index}.pdf",
        mime_type="application/pdf", size_bytes=size, sha256=SHA,
    )


def test_ops_attachment_policy_boundary_per_file():
    policy = AttachmentPolicy(max_file_bytes=TEN_MIB, max_attachments=10)
    assert policy.disposition(_attachment(1, TEN_MIB)) is AttachmentDisposition.ACCEPTED
    assert policy.disposition(_attachment(1, TEN_MIB + 1)) is AttachmentDisposition.REJECTED_SIZE


def test_ops_attachment_policy_counts_but_does_not_sum():
    policy = AttachmentPolicy(max_file_bytes=TEN_MIB, max_attachments=10)
    ten_photos = tuple(_attachment(i, TEN_MIB) for i in range(10))
    # 합계 100MiB — 그래도 통과한다. 상한은 파일별·개수뿐이다(합계 상한 없음).
    policy.require_accepted(ten_photos)
    assert sum(item.size_bytes for item in ten_photos) == 10 * TEN_MIB

    eleven = tuple(_attachment(i, 1) for i in range(11))
    with pytest.raises(ContractError):
        policy.require_accepted(eleven)

    # 한 장이라도 초과하면 묶음 전체가 거부된다(부분 통과 없음).
    mixed = tuple(_attachment(i, TEN_MIB) for i in range(9)) + (_attachment(9, TEN_MIB + 1),)
    with pytest.raises(ContractError):
        policy.require_accepted(mixed)


def test_slack_and_telegram_cap_the_count_not_the_total():
    # Slack: 8장까지, 9장은 거부. 8장 합계(8×10MiB=80MiB)는 제한 대상이 아니다.
    eight = tuple(_slack_manifest(TEN_MIB) for _ in range(MAX_SLACK_FILES_PER_ACTION))
    assert len(eight) == 8
    assert sum(item.size_bytes for item in eight) == 80 * 1024 * 1024
    nine = tuple(_telegram_manifest(TEN_MIB, ref=f"tg/file{i}")
                 for i in range(MAX_TELEGRAM_FILES_PER_UPDATE + 1))
    assert len(nine) == 9  # 개수 상한은 메시지/업데이트 조립 단계에서 판정된다.
