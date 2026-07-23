"""CTO acceptance regression tests for Personal Video Archive.

Covers the final CTO follow-up blockers:
- Real atomic transactions (record + timestamps + proposal status)
- Video detail page without dead routes
- Real feed state-filter UI with inclusion/exclusion
- Date window UI and persistence round trip
- Match reasons rendering
- Topic-video state validation (route + repository)
- Rating validation
- Provider failure visible state (no secret/path leakage)
- Strengthened assertions (no conditional `if match:`, no 500-allowing checks)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c


def _create_topic_and_accept_rule(client, name="Test Topic", intent="test intent"):
    """Helper: create a topic, accept the rule, return topic_id."""
    response = client.post(
        "/topics",
        data={"name": name, "intent": intent},
    )
    assert response.status_code == 200
    match = re.search(r"/topics/([a-f0-9]+)/accept-rule", response.text)
    assert match, "Could not find topic ID in response"
    topic_id = match.group(1)

    client.post(
        f"/topics/{topic_id}/accept-rule",
        data={
            "primary_query": "test",
            "related_queries": "",
            "required_terms": "",
            "excluded_terms": "",
            "preferred_languages": "",
            "included_channels": "",
            "excluded_channels": "",
            "duration_preference": "any",
            "shorts_preference": "include",
            "default_sort": "newest",
            "date_window_start": "",
            "date_window_end": "",
        },
        follow_redirects=False,
    )
    return topic_id


def _sync_topic(client, topic_id):
    """Helper: sync a topic and assert a non-error redirect."""
    response = client.post(f"/topics/{topic_id}/sync", follow_redirects=False)
    assert response.status_code == 303, f"Sync failed: {response.status_code}"
    assert "sync_failed" not in response.headers.get("location", "")
    return response


def _first_tv_id(client, topic_id):
    """Return the first topic-video id from the feed."""
    response = client.get(f"/topics/{topic_id}")
    assert response.status_code == 200
    match = re.search(r"/topic-videos/([a-f0-9]+)/state", response.text)
    assert match, "Could not find any topic-video in the feed"
    return match.group(1)


def _create_record(client, topic_id):
    """Create a record for the first topic-video and return (tv_id, record_id)."""
    tv_id = _first_tv_id(client, topic_id)
    response = client.post(
        f"/topic-videos/{tv_id}/records", follow_redirects=False
    )
    assert response.status_code == 303
    record_id = response.headers["location"].split("/records/")[1]
    return tv_id, record_id


def _parse_feed_articles(html):
    """Return list of (tv_id, title) parsed from feed article blocks."""
    result = []
    for chunk in html.split("<article")[1:]:
        tv_m = re.search(r"/topic-videos/([a-f0-9]+)/state", chunk)
        title_m = re.search(r'data-video-title="([^"]*)"', chunk)
        if tv_m and title_m:
            result.append((tv_m.group(1), title_m.group(1)))
    return result


def _repos(client):
    from app.db import get_connection
    from app.factory import _build_services

    conn = get_connection(client.app.state.db_path)
    return conn, _build_services(conn)


class TestRecordCreation:
    """Record creation/edit workflow."""

    def test_record_creation_from_topic_video(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        tv_id = _first_tv_id(client, topic_id)
        response = client.post(
            f"/topic-videos/{tv_id}/records", follow_redirects=False
        )
        assert response.status_code == 303
        assert "/records/" in response.headers["location"]

        record_id = response.headers["location"].split("/records/")[1]
        response = client.get(f"/records/{record_id}")
        assert response.status_code == 200

    def test_record_duplicate_prevention(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        tv_id = _first_tv_id(client, topic_id)
        r1 = client.post(f"/topic-videos/{tv_id}/records", follow_redirects=False)
        r2 = client.post(f"/topic-videos/{tv_id}/records", follow_redirects=False)
        assert r1.headers["location"] == r2.headers["location"]

    def test_record_creation_nonexistent_tv_rejected(self, client):
        response = client.post(
            "/topic-videos/nonexistent-tv-id/records", follow_redirects=False
        )
        assert response.status_code == 404

    def test_no_dead_link_records_new(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        assert "/records/new" not in client.get(f"/topics/{topic_id}").text
        assert "/records/new" not in client.get("/").text


class TestVideoDetailPage:
    """Fix 2: video detail page uses topic-video scoped routes, no dead routes."""

    def test_video_detail_renders_with_scoped_routes(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id)
            assert feed, "expected at least one topic-video"
            video_id = feed[0][1].id
        finally:
            conn.close()

        response = client.get(f"/videos/{video_id}")
        assert response.status_code == 200

        # Dead routes must be gone.
        assert f"/videos/{video_id}/open" not in response.text
        assert "/records/new" not in response.text

        # Topic-video scoped routes must be present.
        assert re.search(r"/topic-videos/[a-f0-9]+/open", response.text)
        assert re.search(r"/topic-videos/[a-f0-9]+/records", response.text)

    def test_video_detail_not_found(self, client):
        response = client.get("/videos/does-not-exist")
        assert response.status_code == 404


class TestFeedStateFilter:
    """Fix 3: real feed state-filter UI with inclusion/exclusion."""

    def test_feed_has_all_state_filter_options(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        response = client.get(f"/topics/{topic_id}")
        assert response.status_code == 200
        for state in ["all", "unseen", "opened", "saved", "in_progress",
                      "completed", "revisit", "irrelevant"]:
            assert f"?state={state}" in response.text, f"missing filter {state}"

    def test_current_filter_marked_selected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        response = client.get(f"/topics/{topic_id}?state=completed")
        assert response.status_code == 200
        assert "filter-pill-selected" in response.text
        # The completed pill carries the selected marker and aria-current.
        assert re.search(
            r'\?state=completed"[^>]*filter-pill-selected', response.text
        ) or re.search(
            r'filter-pill-selected[^>]*\?state=completed', response.text
        )

    def test_filter_inclusion_exclusion_by_video_id(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        articles = _parse_feed_articles(client.get(f"/topics/{topic_id}").text)
        assert len(articles) >= 2, "need at least two videos to verify filtering"
        target_tv_id, _ = articles[0]

        # Move the first video to completed.
        resp = client.post(
            f"/topic-videos/{target_tv_id}/state",
            data={"state": "completed", "return_state": "all"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Verify by unique topic-video id (titles can repeat across videos).
        completed_ids = [
            tid for tid, _ in _parse_feed_articles(
                client.get(f"/topics/{topic_id}?state=completed").text
            )
        ]
        unseen_ids = [
            tid for tid, _ in _parse_feed_articles(
                client.get(f"/topics/{topic_id}?state=unseen").text
            )
        ]

        # The moved video is included in completed and excluded from unseen.
        assert target_tv_id in completed_ids
        assert target_tv_id not in unseen_ids
        # Other videos remain unseen.
        assert len(unseen_ids) >= 1
        # The two filtered views are disjoint by topic-video id.
        assert set(completed_ids).isdisjoint(set(unseen_ids))

    def test_state_change_preserves_filter(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        tv_id = _first_tv_id(client, topic_id)
        resp = client.post(
            f"/topic-videos/{tv_id}/state",
            data={"state": "saved", "return_state": "saved"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "state=saved" in resp.headers["location"]


class TestTopicVideoOpen:
    """Topic-video scoped open handling."""

    def test_open_only_affects_one_topic_db(self, client):
        topic_id_1 = _create_topic_and_accept_rule(client, name="Topic A")
        topic_id_2 = _create_topic_and_accept_rule(client, name="Topic B")
        _sync_topic(client, topic_id_1)
        _sync_topic(client, topic_id_2)

        response = client.get(f"/topics/{topic_id_1}")
        match = re.search(r"/topic-videos/([a-f0-9]+)/open", response.text)
        assert match, "Could not find open action"
        tv_id_1 = match.group(1)

        resp = client.post(
            f"/topic-videos/{tv_id_1}/open", follow_redirects=False
        )
        assert resp.status_code == 303
        assert "youtube.com" in resp.headers["location"]

        # Compare the actual DB records for both topic-videos of the same video.
        conn, repos = _repos(client)
        try:
            tv1 = repos["topic_video"].get(tv_id_1)
            rec1 = repos["record"].get_by_topic_video(tv_id_1)
            assert rec1 is not None
            assert rec1.viewing_state.value == "opened"

            tv2 = repos["topic_video"].get_by_topic_video(
                topic_id_2, tv1.video_id
            )
            assert tv2 is not None, "same video should exist in topic 2"
            rec2 = repos["record"].get_by_topic_video(tv2.id)
            assert rec2 is None or rec2.viewing_state.value != "opened"
        finally:
            conn.close()

    def test_open_creates_record_if_none(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        response = client.get(f"/topics/{topic_id}")
        match = re.search(r"/topic-videos/([a-f0-9]+)/open", response.text)
        assert match
        tv_id = match.group(1)

        response = client.post(
            f"/topic-videos/{tv_id}/open", follow_redirects=False
        )
        assert response.status_code == 303
        assert "youtube.com" in response.headers["location"]

        conn, repos = _repos(client)
        try:
            rec = repos["record"].get_by_topic_video(tv_id)
            assert rec is not None
            assert rec.viewing_state.value == "opened"
        finally:
            conn.close()

    def test_open_nonexistent_tv_returns_404(self, client):
        response = client.post(
            "/topic-videos/nonexistent/open", follow_redirects=False
        )
        assert response.status_code == 404


class TestOutboundOpenContract:
    """Final CTO blocker: single-tab-safe outbound YouTube opening.

    The open action must be a plain POST form with target="_blank" and no
    JavaScript window.open/fetch, and it must never downgrade an explicit
    user viewing state (completed/irrelevant/...) to `opened`.
    """

    def _open_form_tag(self, html, tv_id):
        """Return the <form ...> opening tag for a topic-video open action."""
        match = re.search(
            r'<form[^>]*action="/topic-videos/' + tv_id + r'/open"[^>]*>',
            html,
        )
        return match.group(0) if match else None

    def test_feed_open_uses_post_form_with_blank_target(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        html = client.get(f"/topics/{topic_id}").text
        tv_id = _first_tv_id(client, topic_id)

        form_tag = self._open_form_tag(html, tv_id)
        assert form_tag is not None, "feed must expose a POST open form"
        assert 'method="post"' in form_tag
        assert 'target="_blank"' in form_tag
        assert f'action="/topic-videos/{tv_id}/open"' in form_tag

    def test_feed_has_no_open_javascript(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        html = client.get(f"/topics/{topic_id}").text
        assert "fetch(" not in html
        assert "window.open(" not in html

    def test_feed_title_is_not_new_tab_anchor(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        html = client.get(f"/topics/{topic_id}").text
        # No anchor may open the canonical YouTube URL in a new tab; opening
        # happens only through the POST form above.
        for anchor in re.findall(r"<a\b[^>]*>", html):
            assert not (
                'target="_blank"' in anchor and "youtube.com" in anchor
            ), f"anchor directly opens YouTube in a new tab: {anchor}"

    def test_detail_open_form_per_topic_video(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id)
            assert feed
            video_id = feed[0][1].id
            tv_ids = [tv.id for tv, _ in feed if tv.video_id == video_id]
        finally:
            conn.close()

        html = client.get(f"/videos/{video_id}").text
        assert tv_ids, "expected at least one topic-video for the video"
        for tv_id in tv_ids:
            form_tag = self._open_form_tag(html, tv_id)
            assert form_tag is not None, (
                f"detail page must have an open form for {tv_id}"
            )
            assert 'method="post"' in form_tag
            assert 'target="_blank"' in form_tag

    def test_detail_has_no_dead_routes_or_js(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id)
            video_id = feed[0][1].id
        finally:
            conn.close()

        html = client.get(f"/videos/{video_id}").text
        assert "window.open(" not in html
        assert f"/videos/{video_id}/open" not in html
        assert "/records/new" not in html

    def test_open_redirects_to_canonical_url(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        tv_id = _first_tv_id(client, topic_id)
        conn, repos = _repos(client)
        try:
            tv = repos["topic_video"].get(tv_id)
            canonical = repos["video"].get(tv.video_id).canonical_url
        finally:
            conn.close()

        resp = client.post(
            f"/topic-videos/{tv_id}/open", follow_redirects=False
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == canonical

    def test_open_unseen_becomes_opened(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        tv_id = _first_tv_id(client, topic_id)

        client.post(f"/topic-videos/{tv_id}/open", follow_redirects=False)

        conn, repos = _repos(client)
        try:
            rec = repos["record"].get_by_topic_video(tv_id)
            assert rec.viewing_state.value == "opened"
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "preserved_state",
        ["completed", "irrelevant", "saved", "in_progress", "revisit"],
    )
    def test_open_preserves_explicit_user_state(self, client, preserved_state):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        tv_id = _first_tv_id(client, topic_id)

        resp = client.post(
            f"/topic-videos/{tv_id}/state",
            data={"state": preserved_state},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Opening must not downgrade an explicit user state.
        client.post(f"/topic-videos/{tv_id}/open", follow_redirects=False)

        conn, repos = _repos(client)
        try:
            rec = repos["record"].get_by_topic_video(tv_id)
            assert rec.viewing_state.value == preserved_state
        finally:
            conn.close()

    def test_open_does_not_touch_other_topic_video(self, client):
        topic_id_1 = _create_topic_and_accept_rule(client, name="Topic A")
        topic_id_2 = _create_topic_and_accept_rule(client, name="Topic B")
        _sync_topic(client, topic_id_1)
        _sync_topic(client, topic_id_2)

        conn, repos = _repos(client)
        try:
            tv1 = repos["topic_video"].list_for_topic(topic_id_1)[0][0]
            tv2 = repos["topic_video"].get_by_topic_video(
                topic_id_2, tv1.video_id
            )
            assert tv2 is not None, "same video should exist in topic 2"
            rec2 = repos["record"].create(tv2.id)
            repos["record"].update(rec2.id, viewing_state="completed")
        finally:
            conn.close()

        client.post(f"/topic-videos/{tv1.id}/open", follow_redirects=False)

        conn, repos = _repos(client)
        try:
            rec1 = repos["record"].get_by_topic_video(tv1.id)
            assert rec1.viewing_state.value == "opened"
            # The other topic-video keeps its explicit completed state.
            rec2 = repos["record"].get_by_topic_video(tv2.id)
            assert rec2.viewing_state.value == "completed"
        finally:
            conn.close()


class TestStateValidation:
    """Fix 6: topic-video state validation at route and repository."""

    def test_invalid_state_returns_400_db_unchanged(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        tv_id = _first_tv_id(client, topic_id)

        response = client.post(
            f"/topic-videos/{tv_id}/state",
            data={"state": "bogus_state"},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert response.status_code != 500

        conn, repos = _repos(client)
        try:
            rec = repos["record"].get_by_topic_video(tv_id)
            assert rec is None or rec.viewing_state.value != "bogus_state"
        finally:
            conn.close()

    def test_repository_rejects_invalid_state(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id)
            tv = feed[0][0]
            rec = repos["record"].create(tv.id)
            with pytest.raises(ValueError):
                repos["record"].update(rec.id, viewing_state="not_a_state")
        finally:
            conn.close()

    def test_valid_state_accepted(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        tv_id = _first_tv_id(client, topic_id)

        response = client.post(
            f"/topic-videos/{tv_id}/state",
            data={"state": "revisit"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            rec = repos["record"].get_by_topic_video(tv_id)
            assert rec.viewing_state.value == "revisit"
        finally:
            conn.close()


class TestRatingValidation:
    """Fix 7: rating must be blank or 1-5."""

    @pytest.mark.parametrize("bad_rating", ["0", "-1", "6", "abc"])
    def test_invalid_rating_returns_400_db_unchanged(self, client, bad_rating):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/update",
            data={
                "viewing_state": "unseen",
                "rating": bad_rating,
                "reflection": "",
                "learned_point": "",
                "agreement": "",
                "disagreement": "",
                "uncertainty": "",
                "follow_up_plan": "",
                "free_form_note": "",
                "tags": "",
                "opened_date": "",
                "completed_date": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert response.status_code != 500

        conn, repos = _repos(client)
        try:
            rec = repos["record"].get(record_id)
            assert rec.rating is None
        finally:
            conn.close()

    def test_valid_rating_persisted(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/update",
            data={
                "viewing_state": "unseen",
                "rating": "4",
                "reflection": "",
                "learned_point": "",
                "agreement": "",
                "disagreement": "",
                "uncertainty": "",
                "follow_up_plan": "",
                "free_form_note": "",
                "tags": "",
                "opened_date": "",
                "completed_date": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            assert repos["record"].get(record_id).rating == 4
        finally:
            conn.close()

    def test_blank_rating_allowed(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/update",
            data={
                "viewing_state": "unseen",
                "rating": "",
                "reflection": "",
                "learned_point": "",
                "agreement": "",
                "disagreement": "",
                "uncertainty": "",
                "follow_up_plan": "",
                "free_form_note": "",
                "tags": "",
                "opened_date": "",
                "completed_date": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303


class TestProposalValidationAndTransaction:
    """Fix 1 & 9: proposal validation and real atomic transaction."""

    def test_excessive_input_does_not_call_provider(self, client, monkeypatch):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        provider = client.app.state.llm_provider
        calls = {"n": 0}
        original = provider.structure_record

        def spy(notes):
            calls["n"] += 1
            return original(notes)

        monkeypatch.setattr(provider, "structure_record", spy)

        response = client.post(
            f"/records/{record_id}/propose-structure",
            data={"rough_notes": "x" * 20001},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert calls["n"] == 0, "provider must not be called for excessive input"

    def test_invalid_proposal_accept_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        long_tag = "a" * 50
        client.post(
            f"/records/{record_id}/propose-structure",
            data={"rough_notes": "reflection: test\ntags: " + long_tag},
            follow_redirects=False,
        )

        response = client.get(f"/records/{record_id}")
        match = re.search(r"/proposals/([a-f0-9]+)/accept", response.text)
        assert match, "expected a pending proposal to accept"
        proposal_id = match.group(1)

        response = client.post(
            f"/proposals/{proposal_id}/accept", follow_redirects=False
        )
        assert response.status_code == 400

    def test_malformed_json_accept_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        client.post(
            f"/records/{record_id}/propose-structure",
            data={"rough_notes": "reflection: test\nplan: do something"},
            follow_redirects=False,
        )

        conn, repos = _repos(client)
        try:
            proposals = [
                p for p in repos["proposal"].list_pending()
                if p.record_id == record_id
            ]
            assert proposals, "expected a pending proposal"
            conn.execute(
                "UPDATE proposals SET proposed_json = 'not valid json' "
                "WHERE id = ?",
                (proposals[0].id,),
            )
            conn.commit()
            proposal_id = proposals[0].id
        finally:
            conn.close()

        response = client.post(
            f"/proposals/{proposal_id}/accept", follow_redirects=False
        )
        assert response.status_code == 400

    def test_accepted_proposal_reaccept_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        client.post(
            f"/records/{record_id}/propose-structure",
            data={"rough_notes": "reflection: test\nplan: do something"},
            follow_redirects=False,
        )

        response = client.get(f"/records/{record_id}")
        match = re.search(r"/proposals/([a-f0-9]+)/accept", response.text)
        assert match
        proposal_id = match.group(1)

        assert client.post(
            f"/proposals/{proposal_id}/accept", follow_redirects=False
        ).status_code == 303
        assert client.post(
            f"/proposals/{proposal_id}/accept", follow_redirects=False
        ).status_code == 400

    def test_rejected_proposal_accept_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        client.post(
            f"/records/{record_id}/propose-structure",
            data={"rough_notes": "reflection: test\nplan: do something"},
            follow_redirects=False,
        )

        response = client.get(f"/records/{record_id}")
        match = re.search(r"/proposals/([a-f0-9]+)/reject", response.text)
        assert match
        proposal_id = match.group(1)

        client.post(f"/proposals/{proposal_id}/reject")
        assert client.post(
            f"/proposals/{proposal_id}/accept", follow_redirects=False
        ).status_code == 400

    def test_accept_rolls_back_on_mid_write_failure(self, tmp_path, monkeypatch):
        """A failure during timestamp processing (after the record update)
        must roll back record fields, timestamps, and proposal status."""
        from app.db import apply_migrations, get_connection
        from app.domain.enums import ProposalType
        from app.domain.models import DiscoveredVideo, QueryRuleProposal
        from app.factory import _build_services
        from app.providers.fake_language_model import FakeLanguageModelProvider
        from app.services import RecordService

        db_path = str(tmp_path / "txn.db")
        conn = get_connection(db_path)
        migrations_dir = str(
            Path(__file__).resolve().parents[2] / "migrations"
        )
        apply_migrations(conn, migrations_dir)
        repos = _build_services(conn)

        topic = repos["topic"].create(name="Txn Topic", intent="txn")
        repos["rule"].create_from_proposal(
            topic.id, QueryRuleProposal(primary_query="txn")
        )
        video = DiscoveredVideo(
            id="vid_txn_1",
            provider="youtube",
            provider_video_id="abcdefghijk",
            canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
            title="Txn Video",
            published_at="2024-01-01T00:00:00Z",
        )
        repos["video"].upsert(video)
        tv = repos["topic_video"].link(topic.id, video.id)
        record = repos["record"].create(tv.id)
        repos["record"].update(record.id, reflection="ORIGINAL", rating=3)

        proposal_json = json.dumps({
            "title": "New Title",
            "summary": "sum",
            "reflection": "NEW_REFLECTION",
            "learned_point": "",
            "agreement": "",
            "disagreement": "",
            "uncertainty": "",
            "follow_up_plan": "",
            "tags": [],
            "timestamp_references": [
                {"timestamp_seconds": 10, "label": "first"},
                {"timestamp_seconds": 20, "label": "second"},
            ],
            "rating": 5,
        })
        proposal = repos["proposal"].create(
            proposal_type=ProposalType.RECORD_STRUCTURE,
            proposed_json=proposal_json,
            record_id=record.id,
        )

        service = RecordService(
            repos["topic_video"], repos["record"], repos["proposal"],
            FakeLanguageModelProvider(),
        )

        original_add = repos["record"].add_timestamp_ref
        calls = {"n": 0}

        def failing_add(record_id, seconds, label="", *, commit=True):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("forced failure during timestamp processing")
            return original_add(record_id, seconds, label, commit=commit)

        monkeypatch.setattr(repos["record"], "add_timestamp_ref", failing_add)

        with pytest.raises(RuntimeError):
            service.accept_structure_proposal(proposal.id)

        # The first timestamp write happened, then the second failed — so this
        # is a genuine mid-write failure, not a pre-validation failure.
        assert calls["n"] == 2

        rolled = repos["record"].get(record.id)
        assert rolled.reflection == "ORIGINAL"
        assert rolled.rating == 3
        assert repos["record"].list_timestamp_refs(record.id) == []
        assert repos["proposal"].get(proposal.id).status.value == "pending"
        conn.close()

    def test_rule_change_accept_is_atomic(self, tmp_path, monkeypatch):
        """Rule update + proposal acceptance commit together; a failure after
        the rule write rolls back both."""
        from app.db import apply_migrations, get_connection
        from app.domain.enums import ProposalStatus, ProposalType
        from app.domain.models import QueryRuleProposal
        from app.factory import _build_services
        from app.providers.fake_language_model import FakeLanguageModelProvider
        from app.services import ProposalService

        db_path = str(tmp_path / "rule_txn.db")
        conn = get_connection(db_path)
        migrations_dir = str(
            Path(__file__).resolve().parents[2] / "migrations"
        )
        apply_migrations(conn, migrations_dir)
        repos = _build_services(conn)

        topic = repos["topic"].create(name="Rule Topic", intent="rule")
        rule = repos["rule"].create_from_proposal(
            topic.id, QueryRuleProposal(primary_query="rule")
        )
        proposal_json = json.dumps({
            "added_excluded_terms": ["spam"],
            "added_related_queries": [],
            "preferred_channels": [],
            "excluded_channels": [],
            "exclude_shorts": False,
            "date_window_start": None,
            "date_window_end": None,
            "duration_preference": None,
            "rationale": "test",
        })
        proposal = repos["proposal"].create(
            proposal_type=ProposalType.RULE_CHANGE,
            proposed_json=proposal_json,
            topic_id=topic.id,
        )

        service = ProposalService(
            repos["topic"], repos["rule"], repos["proposal"],
            FakeLanguageModelProvider(),
        )

        original_status = repos["proposal"].update_status

        def failing_status(proposal_id, status, *, commit=True):
            raise RuntimeError("forced failure after rule write")

        monkeypatch.setattr(repos["proposal"], "update_status", failing_status)

        with pytest.raises(RuntimeError):
            service.accept_rule_change(proposal.id)

        # Rule must NOT have gained the excluded term, proposal stays pending.
        rolled_rule = repos["rule"].get(rule.id)
        assert "spam" not in rolled_rule.excluded_terms
        assert repos["proposal"].get(proposal.id).status == (
            ProposalStatus.PENDING
        )

        # Without the failure, both apply together.
        monkeypatch.setattr(repos["proposal"], "update_status", original_status)
        service.accept_rule_change(proposal.id)
        assert "spam" in repos["rule"].get(rule.id).excluded_terms
        assert repos["proposal"].get(proposal.id).status == (
            ProposalStatus.ACCEPTED
        )
        conn.close()


class TestProviderUnavailable:
    """Fix 8: provider failure visible state, no leakage."""

    def _flaky_app(self, tmp_path):
        from app.providers.fake_language_model import FakeLanguageModelProvider
        from app.providers.fake_video_discovery import FakeVideoDiscoveryProvider

        class FlakyProvider:
            def __init__(self):
                self.calls = 0
                self._real = FakeVideoDiscoveryProvider()

            def search_videos(self, rules, cursor=None):
                self.calls += 1
                if self.calls >= 2:
                    raise RuntimeError("provider down SECRET_KEY=xyz /etc/passwd")
                return self._real.search_videos(rules, cursor)

            def get_video_details(self, ids):
                return self._real.get_video_details(ids)

        db_path = str(tmp_path / "flaky.db")
        app = create_app(
            db_path=db_path,
            discovery_provider=FlakyProvider(),
            llm_provider=FakeLanguageModelProvider(),
        )
        return app

    def test_provider_failure_preserves_feed_and_shows_message(self, tmp_path):
        app = self._flaky_app(tmp_path)
        with TestClient(app, raise_server_exceptions=False) as ac:
            topic_id = _create_topic_and_accept_rule(ac)

            # First sync succeeds and populates the feed.
            ac.post(f"/topics/{topic_id}/sync", follow_redirects=False)
            titles_before = [
                t for _, t in _parse_feed_articles(
                    ac.get(f"/topics/{topic_id}").text
                )
            ]
            assert len(titles_before) >= 1

            # Second sync fails.
            resp = ac.post(f"/topics/{topic_id}/sync", follow_redirects=False)
            assert resp.status_code == 303
            assert resp.status_code != 500
            assert "sync_failed=1" in resp.headers["location"]

            feed = ac.get(resp.headers["location"])
            assert feed.status_code == 200
            # User-facing message is shown.
            assert "새로고침 실패" in feed.text
            # Existing feed is preserved.
            titles_after = [
                t for _, t in _parse_feed_articles(feed.text)
            ]
            assert titles_after == titles_before
            # No internal details leak.
            assert "SECRET_KEY" not in feed.text
            assert "/etc/passwd" not in feed.text
            assert "Traceback" not in feed.text

    def test_provider_failure_records_failed_sync(self, tmp_path):
        from app.db import get_connection
        from app.factory import _build_services

        app = self._flaky_app(tmp_path)
        with TestClient(app, raise_server_exceptions=False) as ac:
            topic_id = _create_topic_and_accept_rule(ac)
            ac.post(f"/topics/{topic_id}/sync", follow_redirects=False)
            ac.post(f"/topics/{topic_id}/sync", follow_redirects=False)

            conn = get_connection(app.state.db_path)
            repos = _build_services(conn)
            try:
                runs = repos["sync"].list_for_topic(topic_id)
                assert any(r.status.value == "failed" for r in runs)
            finally:
                conn.close()

    def test_invalid_state_form_does_not_pollute_db(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/update",
            data={
                "viewing_state": "invalid_state",
                "reflection": "test",
                "learned_point": "",
                "agreement": "",
                "disagreement": "",
                "uncertainty": "",
                "follow_up_plan": "",
                "free_form_note": "",
                "tags": "",
                "opened_date": "",
                "completed_date": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400

        conn, repos = _repos(client)
        try:
            assert repos["record"].get(record_id).viewing_state.value == "unseen"
        finally:
            conn.close()


class TestMatchAnalysis:
    """Fix 5: match score and reasons rendering."""

    def test_match_score_persisted(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id)
            assert feed
            assert feed[0][0].match_score is not None
        finally:
            conn.close()

    def test_match_reasons_rendered_in_feed(self, client):
        from markupsafe import escape

        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id)
            reason_text = None
            for tv, _ in feed:
                if tv.match_reasons:
                    reason_text = tv.match_reasons[0]
                    break
            assert reason_text, "expected at least one topic-video with reasons"
        finally:
            conn.close()

        response = client.get(f"/topics/{topic_id}")
        assert "Application analysis" in response.text
        # Jinja autoescapes the reason (e.g. apostrophes -> &#39;), so compare
        # against the escaped form to prove the reason string is actually rendered.
        assert str(escape(reason_text)) in response.text

    def test_relevance_sorting_uses_match_score(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _sync_topic(client, topic_id)

        conn, repos = _repos(client)
        try:
            feed = repos["topic_video"].list_for_topic(topic_id, sort="relevance")
            assert feed
            scores = [tv.match_score for tv, _ in feed]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1]
        finally:
            conn.close()


class TestDateWindow:
    """Fix 4: date window UI and persistence round trip."""

    def test_date_window_inputs_rendered(self, client):
        response = client.post(
            "/topics",
            data={"name": "DW", "intent": "videos about python from 2024"},
        )
        assert response.status_code == 200
        assert 'name="date_window_start"' in response.text
        assert 'name="date_window_end"' in response.text

    def test_date_window_proposal_value_rendered(self, tmp_path):
        from app.domain.models import QueryRuleProposal
        from app.providers.fake_language_model import FakeLanguageModelProvider

        class DatingLLM(FakeLanguageModelProvider):
            def propose_query_rules(self, intent):
                p = super().propose_query_rules(intent)
                return QueryRuleProposal(
                    primary_query=p.primary_query,
                    related_queries=p.related_queries,
                    required_terms=p.required_terms,
                    excluded_terms=p.excluded_terms,
                    preferred_languages=p.preferred_languages,
                    duration_preference=p.duration_preference,
                    shorts_preference=p.shorts_preference,
                    default_sort=p.default_sort,
                    date_window_start="2024-03-01",
                    date_window_end="2024-09-30",
                    rationale=p.rationale,
                )

        db_path = str(tmp_path / "dw.db")
        app = create_app(db_path=db_path, llm_provider=DatingLLM())
        with TestClient(app) as ac:
            resp = ac.post(
                "/topics", data={"name": "DW", "intent": "python videos"}
            )
            assert resp.status_code == 200
            assert 'value="2024-03-01"' in resp.text
            assert 'value="2024-09-30"' in resp.text

    def test_date_window_round_trip(self, client):
        response = client.post(
            "/topics", data={"name": "DW Topic", "intent": "2024 videos"}
        )
        match = re.search(r"/topics/([a-f0-9]+)/accept-rule", response.text)
        assert match
        topic_id = match.group(1)

        response = client.post(
            f"/topics/{topic_id}/accept-rule",
            data={
                "primary_query": "test",
                "related_queries": "",
                "required_terms": "",
                "excluded_terms": "",
                "preferred_languages": "",
                "included_channels": "",
                "excluded_channels": "",
                "duration_preference": "any",
                "shorts_preference": "include",
                "default_sort": "newest",
                "date_window_start": "2024-01-01",
                "date_window_end": "2024-12-31",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            rule = repos["rule"].get_active(topic_id)
            assert rule.date_window_start == "2024-01-01"
            assert rule.date_window_end == "2024-12-31"
        finally:
            conn.close()

    def test_date_window_invalid_format_rejected(self, client):
        response = client.post(
            "/topics", data={"name": "Test", "intent": "test"}
        )
        match = re.search(r"/topics/([a-f0-9]+)/accept-rule", response.text)
        assert match
        topic_id = match.group(1)

        response = client.post(
            f"/topics/{topic_id}/accept-rule",
            data={
                "primary_query": "test",
                "duration_preference": "any",
                "shorts_preference": "include",
                "default_sort": "newest",
                "date_window_start": "not-a-date",
                "date_window_end": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400

    def test_date_window_start_after_end_rejected(self, client):
        response = client.post(
            "/topics", data={"name": "Test", "intent": "test"}
        )
        match = re.search(r"/topics/([a-f0-9]+)/accept-rule", response.text)
        assert match
        topic_id = match.group(1)

        response = client.post(
            f"/topics/{topic_id}/accept-rule",
            data={
                "primary_query": "test",
                "duration_preference": "any",
                "shorts_preference": "include",
                "default_sort": "newest",
                "date_window_start": "2024-12-31",
                "date_window_end": "2024-01-01",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400


class TestUnicodeTags:
    """Unicode-safe tags."""

    def test_korean_tag_accepted(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/update",
            data={
                "viewing_state": "unseen",
                "reflection": "test",
                "learned_point": "",
                "agreement": "",
                "disagreement": "",
                "uncertainty": "",
                "follow_up_plan": "",
                "free_form_note": "",
                "tags": "챗GPT, 가격비교, 다시보기",
                "opened_date": "",
                "completed_date": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            record = repos["record"].get(record_id)
            assert "챗GPT" in record.tags
            assert "가격비교" in record.tags
            assert "다시보기" in record.tags
        finally:
            conn.close()

    def test_mixed_unicode_tags_accepted(self, client):
        from app.domain.models import validate_tags
        tags = validate_tags(["ChatGPT", "챗GPT", "가격비교", "GPT-5", "로컬_LLM"])
        assert len(tags) == 5

    def test_empty_tag_rejected(self, client):
        from app.domain.models import validate_tags
        with pytest.raises(ValueError):
            validate_tags([""])

    def test_duplicate_tag_rejected(self, client):
        from app.domain.models import validate_tags
        with pytest.raises(ValueError):
            validate_tags(["test", "test"])

    def test_control_char_tag_rejected(self, client):
        from app.domain.models import validate_tags
        with pytest.raises(ValueError):
            validate_tags(["test\x00tag"])

    def test_html_tag_rejected(self, client):
        from app.domain.models import validate_tags
        with pytest.raises(ValueError):
            validate_tags(["<script>alert(1)</script>"])


class TestManualTimestamp:
    """Manual timestamp input."""

    def test_add_timestamp_mmss(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/timestamps",
            data={"time_input": "08:24", "label": "가격 비교 설명"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            timestamps = repos["record"].list_timestamp_refs(record_id)
            assert len(timestamps) == 1
            assert timestamps[0].timestamp_seconds == 504
            assert timestamps[0].label == "가격 비교 설명"
        finally:
            conn.close()

    def test_add_timestamp_seconds(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/timestamps",
            data={"time_input": "504", "label": "test"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            timestamps = repos["record"].list_timestamp_refs(record_id)
            assert len(timestamps) == 1
            assert timestamps[0].timestamp_seconds == 504
        finally:
            conn.close()

    def test_add_timestamp_negative_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/timestamps",
            data={"time_input": "-10", "label": "test"},
            follow_redirects=False,
        )
        assert response.status_code == 400

    def test_add_timestamp_invalid_format_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        response = client.post(
            f"/records/{record_id}/timestamps",
            data={"time_input": "not-a-time", "label": "test"},
            follow_redirects=False,
        )
        assert response.status_code == 400

    def test_delete_timestamp(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        _, record_id = _create_record(client, topic_id)

        client.post(
            f"/records/{record_id}/timestamps",
            data={"time_input": "08:24", "label": "test"},
        )

        conn, repos = _repos(client)
        try:
            timestamps = repos["record"].list_timestamp_refs(record_id)
            assert len(timestamps) == 1
            ts_id = timestamps[0].id
        finally:
            conn.close()

        response = client.post(
            f"/records/{record_id}/timestamps/{ts_id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        conn, repos = _repos(client)
        try:
            assert repos["record"].list_timestamp_refs(record_id) == []
        finally:
            conn.close()

    def test_delete_timestamp_from_other_record_rejected(self, client):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)

        response = client.get(f"/topics/{topic_id}")
        matches = re.findall(r"/topic-videos/([a-f0-9]+)/records", response.text)
        assert len(matches) >= 2, "need at least 2 topic-videos"

        r1 = client.post(
            f"/topic-videos/{matches[0]}/records", follow_redirects=False
        )
        record_id_1 = r1.headers["location"].split("/records/")[1]
        r2 = client.post(
            f"/topic-videos/{matches[1]}/records", follow_redirects=False
        )
        record_id_2 = r2.headers["location"].split("/records/")[1]

        client.post(
            f"/records/{record_id_1}/timestamps",
            data={"time_input": "08:24", "label": "test"},
            follow_redirects=False,
        )

        conn, repos = _repos(client)
        try:
            ts_id = repos["record"].list_timestamp_refs(record_id_1)[0].id
        finally:
            conn.close()

        response = client.post(
            f"/records/{record_id_2}/timestamps/{ts_id}/delete",
        )
        assert response.status_code == 404


class TestHealthRoute:
    def test_health_shows_actual_providers(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "FakeVideoDiscoveryProvider" in data["discovery_provider"]
        assert "FakeLanguageModelProvider" in data["llm_provider"]


class TestRecordSearchStateRendering:
    """Gap 2: the records-search badge must show the user-facing state value,
    never the raw ``ViewingState.X`` enum repr, in the live app."""

    @pytest.mark.parametrize("state", ["saved", "completed", "in_progress"])
    def test_search_badge_shows_state_value_not_enum(self, client, state):
        topic_id = _create_topic_and_accept_rule(client)
        _sync_topic(client, topic_id)
        tv_id, _record_id = _create_record(client, topic_id)

        resp = client.post(
            f"/topic-videos/{tv_id}/state",
            data={"state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        response = client.get("/records")
        assert response.status_code == 200
        assert f'<span class="badge badge-user">{state}</span>' in response.text
        assert "ViewingState." not in response.text
