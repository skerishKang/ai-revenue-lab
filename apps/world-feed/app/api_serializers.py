"""JSON serializers for the World Feed HTTP API."""


def source_json(rec):
    return {
        "source_id": rec.source_id,
        "canonical_key": rec.canonical_key,
        "source_state": rec.source_state,
        "country": rec.country,
    }


def reader_json(rec):
    return {
        "reader_id": rec.reader_id,
        "display_name": rec.display_name,
        "language": rec.language,
        "active": rec.active,
    }


def feedback_json(rec):
    return {
        "id": rec.id,
        "reader_id": rec.reader_id,
        "action": rec.action,
        "idempotency_key": rec.idempotency_key,
        "applied_to_brief_id": rec.applied_to_brief_id,
    }


def brief_json(rec):
    return {
        "id": rec.id,
        "brief_number": rec.brief_number,
        "reader_id": rec.reader_id,
        "sequence": rec.sequence,
        "status": rec.status,
        "title": rec.title,
        "selected_event_ids": rec.selected_event_ids,
        "feedback_id": rec.feedback_id,
        "validation_status": rec.validation_status,
    }
