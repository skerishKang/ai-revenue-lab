"""Validate generated brief content against selected events and sources."""

from __future__ import annotations

from app.domain.enums import SourceState
from app.domain.models import BriefContent
from app.repositories import source_repository


def validate_content_against_selection(content: BriefContent, selected_map):
    cited = {item.event_id for item in content.items}
    if not cited.issubset(set(selected_map.keys())):
        return False, "brief cites an event outside the selected set"
    for item in content.items:
        ev = selected_map.get(item.event_id)
        if ev is None:
            return False, "brief cites unknown event"
        if ev.status in (SourceState.WITHDRAWN, SourceState.SUPERSEDED):
            return False, "brief cites a non-eligible event"
    conflicting_ids = {
        eid
        for eid, ev in selected_map.items()
        if ev.status == SourceState.CONFLICTING
    }
    if conflicting_ids:
        joined = " ".join(content.uncertainty_notes)
        for item in content.items:
            if item.event_id in conflicting_ids and item.event_id not in joined:
                return (
                    False,
                    "conflicting event cited without an uncertainty note",
                )
    return True, "ok"


def validate_source_grounding(content: BriefContent, selected_map, conn):
    for item in content.items:
        ev = selected_map.get(item.event_id)
        if ev is None:
            return False, f"brief cites unknown event {item.event_id}"
        event_source_ids = set(ev.source_ids)
        if not item.source_ids:
            return False, f"item for {item.event_id} has empty source_ids"
        seen = set()
        for sid in item.source_ids:
            if sid in seen:
                return (
                    False,
                    f"duplicate source_id {sid} in item for {item.event_id}",
                )
            seen.add(sid)
            if sid not in event_source_ids:
                return (
                    False,
                    f"source_id {sid} not part of cited event {item.event_id}",
                )
            src = source_repository.get_source_by_id(conn, sid)
            if src is None:
                return False, f"source_id {sid} does not exist"
            if src.source_state in (
                SourceState.WITHDRAWN.value,
                SourceState.SUPERSEDED.value,
            ):
                return (
                    False,
                    f"source_id {sid} is {src.source_state} and cannot be cited",
                )
    return True, "ok"
