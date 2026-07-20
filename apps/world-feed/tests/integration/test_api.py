import tempfile

from fastapi.testclient import TestClient

from app.ai.mock import MockProvider
from app.config import settings
from app.domain.enums import CostClass
from app.domain.models import ProviderResult
from app.factory import create_app


class _EchoProvider(MockProvider):
    def __init__(self, *, source_ids_map=None, model="mock-world-feed-v1"):
        super().__init__(model=model)
        self._source_ids_map = source_ids_map or {}

    def generate_structured(self, *, task_name, system_prompt, user_payload, response_schema, request_id):
        events = user_payload.get("eligible_events", [])
        items = []
        for e in events:
            sids = self._source_ids_map.get(e["event_id"], ["s1"])
            items.append({
                "event_id": e["event_id"],
                "headline": e["title"],
                "explanation": "x",
                "source_ids": sids,
            })
        payload = {
            "brief_title": task_name,
            "deck": "d",
            "items": items,
            "uncertainty_notes": [e["event_id"] for e in events if e.get("uncertainty")],
            "feedback_note": (user_payload.get("feedback") or {}).get("action"),
        }
        validated = response_schema.model_validate(payload)
        return ProviderResult(
            provider="mock", advertised_model=self._model,
            cost_class=CostClass.FREE, latency_seconds=0.0, retry_count=0,
            payload=validated.model_dump(), request_id=request_id, success=True,
        )


def _source(card_id, key, category, state="single_source"):
    return {
        "source_id": card_id,
        "country": "Vietnam",
        "locality": "Hanoi",
        "original_language": "ko",
        "source_tier": "primary_official",
        "publisher_name": "Pub",
        "organization_type": "tourism_authority",
        "canonical_url": f"https://example.invalid/{card_id}",
        "publication_timestamp": "2026-01-01T00:00:00Z",
        "access_timestamp": "2026-01-02T00:00:00Z",
        "title": "T",
        "text_extract": "E",
        "category": category,
        "media_rights_state": "clear",
        "source_state": state,
        "canonical_key": key,
        "checksum": f"cs-{card_id}",
        "synthetic_flag": True,
    }


class TestWorldFeedApi:
    def test_full_loop_over_http(self):
        path = tempfile.mktemp(suffix=".db")
        app = create_app(db_path=path, provider=_EchoProvider(model=settings.ai_model))
        with TestClient(app) as c:
            assert c.get("/health").json()["status"] == "ok"
            assert c.post("/sources", json=_source("s1", "ev-1", "place_culture")).status_code == 200
            resolve_resp = c.post("/sources/resolve")
            assert resolve_resp.json()["canonical_events"] == 1
            r = {
                "reader_id": "r1",
                "display_name": "R",
                "language": "ko",
                "preferences": {
                    "interests": ["place_culture"],
                    "excluded_categories": [],
                    "desired_coverage": [],
                    "detail_level": "standard",
                    "language": "ko",
                },
                "active": True,
            }
            assert c.post("/readers", json=r).status_code == 200
            first_resp = c.post("/readers/r1/briefs/first")
            assert first_resp.status_code == 200
            first_data = first_resp.json()
            fb = {
                "feedback_id": "f1",
                "reader_id": "r1",
                "idempotency_key": "idem-1",
                "action": "increase_culture_neighborhood",
                "detail": "x",
                "prior_brief_id": first_data["id"],
            }
            assert c.post("/feedback", json=fb).status_code == 200
            second_resp = c.post(
                "/readers/r1/briefs/second",
                json={"feedback_idempotency_key": "idem-1"},
            )
            assert second_resp.status_code == 200
            briefs = c.get("/readers/r1/briefs").json()
            assert [b["sequence"] for b in briefs] == ["first", "second"]
            assert all(b["status"] == "pending_review" for b in briefs)

    def test_invalid_source_rejected(self):
        path = tempfile.mktemp(suffix=".db")
        app = create_app(db_path=path, provider=_EchoProvider(model=settings.ai_model))
        with TestClient(app) as c:
            bad = _source("s1", "ev-1", "place_culture")
            bad["synthetic_flag"] = False
            resp = c.post("/sources", json=bad)
            assert resp.status_code == 422
