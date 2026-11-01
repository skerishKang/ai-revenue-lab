"""#6446 2차 — 큐 내부 상점 문(door)의 소유자 격리.

큐의 내부 상점 RPC(`/internal/store`, 서비스 시크릿 문)는 페어링 스토어 메서드를
이름으로 노출한다. 메서드마다 소유자(user_id) 인자가 강제되고, 소유권은 문서 행의
`user_id`가 결정한다(스토어가 "no such link"과 "not your link"을 구분). 이 시험은
A의 페어링 링크가 B의 이름으로는 목록·해제·일시정지에 전혀 닿지 않음을 고정한다.
서비스 시크릿 자체의 요구는 test_queue_internal_store_rpc.py가 이미 고정한다.
"""
from __future__ import annotations

from test_queue_internal_store_rpc import _app, _body, _call

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
NOW = "2026-11-01T00:00:00.000Z"
NODE_A = "node//a-pc-6446"


def _link_a(app) -> str:
    issued = _body(_call(app, {"method": "issue_code",
                               "arguments": {"user_id": USER_A, "issued_at": NOW}}))
    code = issued["result"]["code"]
    redeemed = _body(_call(app, {"method": "redeem_code", "arguments": {
        "code": code, "mesh_node_id": NODE_A, "label": "A의 PC", "now": NOW,
        "verified": True,
    }}))
    assert redeemed["ok"] is True, redeemed
    links = _body(_call(app, {"method": "list_links",
                              "arguments": {"user_id": USER_A}}))["result"]
    assert links, "the redeemed link must be listed for its owner"
    row = links[0]
    return row.get("link_id") or row.get("id")


def _link_ids(client_response) -> list[str]:
    return [row.get("link_id") or row.get("id") for row in client_response]


def test_the_internal_store_answers_links_per_owner():
    app = _app()
    link_id = _link_a(app)

    listed_b = _body(_call(app, {"method": "list_links",
                                 "arguments": {"user_id": USER_B}}))
    assert listed_b["ok"] is True
    assert link_id not in _link_ids(listed_b["result"])

    listed_a = _body(_call(app, {"method": "list_links",
                                 "arguments": {"user_id": USER_A}}))
    assert _link_ids(listed_a["result"]) == [link_id]


def test_owner_b_cannot_revoke_or_pause_the_links_of_owner_a():
    app = _app()
    link_id = _link_a(app)

    # B의 이름으로 해제를 부르면 UPDATE의 WHERE user_id가 소유권을 행에서 결정해
    # 아무것도 바꾸지 않는다 — 응답은 result=False(이 호출이 해제한 것 없음)다.
    revoked = _body(_call(app, {"method": "revoke_link", "arguments": {
        "user_id": USER_B, "link_id": link_id, "now": NOW}}))
    assert revoked["ok"] is True and revoked["result"] is False, revoked

    # 일시정지는 행 소유자가 아니면 스토어가 "not your link"으로 거절하고, 내부 문은
    # 이유를 반복하지 않은 채 닫는다.
    paused = _call(app, {"method": "pause_link", "arguments": {
        "user_id": USER_B, "link_id": link_id, "now": NOW}})
    assert paused.status_code in (403, 502), paused.status_code

    # A의 링크는 해제·일시정지되지 않고 그대로 남는다.
    listed_a = _body(_call(app, {"method": "list_links",
                                 "arguments": {"user_id": USER_A}}))["result"]
    row = [item for item in listed_a if _link_ids([item]) == [link_id]][0]
    # 클레임 뒤 검증 전 상태(pending_verification)여도 해제·일시정지는 없었다.
    assert row.get("state") in ("active", "pending_verification")
    assert row.get("paused_at") is None


def test_owner_a_still_controls_their_own_link():
    app = _app()
    link_id = _link_a(app)

    paused = _body(_call(app, {"method": "pause_link", "arguments": {
        "user_id": USER_A, "link_id": link_id, "now": NOW}}))
    assert paused["ok"] is True
    resumed = _body(_call(app, {"method": "resume_link", "arguments": {
        "user_id": USER_A, "link_id": link_id, "now": NOW}}))
    assert resumed["ok"] is True
    revoked = _body(_call(app, {"method": "revoke_link", "arguments": {
        "user_id": USER_A, "link_id": link_id, "now": NOW}}))
    assert revoked["ok"] is True and revoked["result"] is True
    listed_a = _body(_call(app, {"method": "list_links",
                                 "arguments": {"user_id": USER_A}}))["result"]
    mine = [row for row in listed_a if _link_ids([row]) == [link_id]]
    assert mine == [] or mine[0].get("state") == "revoked"
