"""#3330 metadata work tickets: no provider, no token, no authorization side effects."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core.drive_index_freshness import DriveIndexSourceSnapshot
from padiem_ai_core.ephemeral_work_ticket import (
    EphemeralExecutionWorkTicket,
    MAX_WORK_TICKET_INPUTS,
    MAX_WORK_TICKET_TTL_SECONDS,
    WorkTicketContractError,
)


START = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)


def _source(file_id="test_drive_file_01", *, version=7, drive_id=None):
    return DriveIndexSourceSnapshot(
        file_id=file_id,
        mime_type="application/pdf",
        drive_id=drive_id,
        version=version,
        modified_time=None,
        md5_checksum=None,
        sha256_checksum=None,
        head_revision_id=None,
    )


def _ticket(**changes):
    values = dict(
        run_ref="run_3330_demo",
        owner_ref="usr_test_3330",
        workspace_ref="workspace_test_3330",
        capability="document.inspect",
        mode="inspect",
        inputs=(_source(),),
        output_folder_ref=None,
        issued_at=START,
        expires_at=START + timedelta(minutes=10),
    )
    values.update(changes)
    return EphemeralExecutionWorkTicket(**values)


def test_metadata_only_ticket_has_no_provider_or_authority_and_is_immutable():
    ticket = _ticket()
    assert ticket.inputs[0] == _source()
    assert ticket.is_within_time_window(START)
    assert ticket.is_within_time_window(START + timedelta(minutes=9))
    assert not ticket.is_within_time_window(START + timedelta(minutes=10))
    assert not ticket.is_within_time_window(START - timedelta(seconds=1))
    assert not hasattr(ticket, "access_token")
    assert not hasattr(ticket, "oauth_refresh_token")
    assert not hasattr(ticket, "provider_secret")
    assert not hasattr(ticket, "execute")
    assert not hasattr(ticket, "dispatch")
    assert not hasattr(ticket, "backend")
    assert not hasattr(ticket, "approve")
    assert not hasattr(ticket, "grant")
    with pytest.raises(FrozenInstanceError):
        ticket.owner_ref = "foreign"


def test_produce_artifact_names_only_candidate_folder_not_drive_write_authority():
    ticket = _ticket(mode="produce_artifact", output_folder_ref="folder_987")
    assert ticket.output_folder_ref == "folder_987"
    with pytest.raises(WorkTicketContractError):
        _ticket(mode="produce_artifact")
    with pytest.raises(WorkTicketContractError):
        _ticket(mode="inspect", output_folder_ref="folder_987")


@pytest.mark.parametrize("field", ["run_ref", "owner_ref", "workspace_ref"])
@pytest.mark.parametrize("bad", ["", " https://example.com", "token/credential", "line\nbreak", "x" * 130])
def test_refused_unsafe_context_references(field, bad):
    with pytest.raises(WorkTicketContractError):
        _ticket(**{field: bad})


@pytest.mark.parametrize("bad", ["", "WRITE/SEND", "document;write", "x" * 130, None, []])
def test_refused_capability(bad):
    with pytest.raises(WorkTicketContractError):
        _ticket(capability=bad)


@pytest.mark.parametrize("bad", ["write", "", None, [], 0, "approve"])
def test_refused_unknown_mode(bad):
    with pytest.raises(WorkTicketContractError):
        _ticket(mode=bad)


@pytest.mark.parametrize(
    "inputs",
    [
        [],
        (),
        (_source(),) * (MAX_WORK_TICKET_INPUTS + 1),
        (_source(), _source()),
        (_source(file_id="https://drive.google.com/file/d/abc"),),
        (_source(file_id="bad/file/id"),),
        (_source(file_id="file_test", drive_id="bad/drive"),),
        (_source(version=None),),
        ({"file_id": "file_123"},),
        ("raw bytes",),
    ],
)
def test_bad_or_unversioned_drive_input_never_becomes_a_work_ticket(inputs):
    with pytest.raises(WorkTicketContractError):
        _ticket(inputs=inputs)


def test_two_distinct_versioned_drive_refs_preserved_in_order():
    t = _ticket(inputs=(
        _source("one", version=3),
        _source("two", version=8, drive_id="drive_123"),
    ))
    assert [x.file_id for x in t.inputs] == ["one", "two"]
    assert t.inputs[1].drive_id == "drive_123"


@pytest.mark.parametrize(
    "start,end",
    [
        (START, START),
        (START, START - timedelta(seconds=1)),
        (START, START + timedelta(seconds=MAX_WORK_TICKET_TTL_SECONDS + 1)),
        (START.replace(tzinfo=None), START + timedelta(minutes=1)),
        (START, (START + timedelta(minutes=1)).replace(tzinfo=None)),
    ],
)
def test_ticket_clock_is_finite_bounded_and_aware(start, end):
    with pytest.raises(WorkTicketContractError):
        _ticket(issued_at=start, expires_at=end)


def test_clock_validation_rejects_naive_now_and_allows_aware_offset():
    ticket = _ticket()
    with pytest.raises(WorkTicketContractError):
        ticket.is_within_time_window(START.replace(tzinfo=None))
    tz = timezone(timedelta(hours=9))
    assert ticket.is_within_time_window((START + timedelta(minutes=5)).astimezone(tz))


def test_dataclass_has_closed_constructor_no_token_or_approval_fields():
    with pytest.raises(TypeError):
        _ticket(access_token="do-not-allow")
    with pytest.raises(TypeError):
        _ticket(approved=True)
    with pytest.raises(WorkTicketContractError):
        replace(_ticket(), output_folder_ref="https://oauth.example/credential")
