"""#5573 follow-up: a paused PC link takes no work, and un-pausing puts it back.

The Owner's rule is that the connected PC is used at full-drive scope and that
work is not gated behind a per-task approval. Pause is therefore a state the
account chooses once, not a confirmation step it repeats: it has to hold against
every read the dispatch lane makes, it must not cost the folder approvals, and it
must not add a second way to fail.

These checks cover exactly that:

  * a paused link disappears from all three dispatch reads at once;
  * resume restores it, and pausing twice is the same answer rather than an error;
  * the two new routes answer a plain POST with no body and no confirmation
    field, because a pause is not a privilege escalation;
  * another account's link is refused as a permission failure (403), an unknown
    link as a missing one (404), and a revoked link cannot be paused;
  * disconnect keeps using the existing DELETE and still drops the approvals.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_5573_pc_device_pairing as pairing  # noqa: E402
from app.pc_device_pairing_routes import (  # noqa: E402
    PC_PAIRING_PAUSE_PATH,
    PC_PAIRING_RESUME_PATH,
)

ROOT = "C:\\Users\\owner\\Documents"


async def _adopt(store, *, user_id: str = pairing.OWNER, node: str = pairing.NODE) -> str:
    link = await store.adopt_link(
        user_id=user_id, mesh_node_id=node, root_paths=[ROOT], now=pairing._now(),
    )
    return str(link["link_id"])


def _adopted(store, **values) -> str:
    """The sync wrapper, for the tests that drive the store without HTTP."""
    return pairing.run(_adopt(store, **values))


def test_pause_clears_the_link_from_every_dispatch_read() -> None:
    store = pairing.store()
    link_id = _adopted(store)
    assert pairing.run(store.links_for_owner(user_id=pairing.OWNER))
    assert pairing.run(store.device_scope(device_id=pairing.NODE)) is not None
    assert pairing.run(store.link_for(user_id=pairing.OWNER, mesh_node_id=pairing.NODE))

    paused = pairing.run(store.pause_link(
        user_id=pairing.OWNER, link_id=link_id, now=pairing._now(),
    ))
    assert paused["paused"] is True and paused["paused_at"]
    assert pairing.run(store.links_for_owner(user_id=pairing.OWNER)) == []
    assert pairing.run(store.device_scope(device_id=pairing.NODE)) is None
    assert pairing.run(store.link_for(user_id=pairing.OWNER, mesh_node_id=pairing.NODE)) is None


def test_resume_puts_the_same_link_back_without_a_new_grant() -> None:
    store = pairing.store()
    link_id = _adopted(store)
    before = pairing.run(store.list_links(user_id=pairing.OWNER))
    pairing.run(store.pause_link(user_id=pairing.OWNER, link_id=link_id, now=pairing._now()))
    again = pairing.run(store.pause_link(user_id=pairing.OWNER, link_id=link_id, now=pairing._now()))
    assert again["paused"] is True, "a second pause is the same answer, not an error"

    resumed = pairing.run(store.resume_link(
        user_id=pairing.OWNER, link_id=link_id, now=pairing._now(),
    ))
    assert resumed["paused"] is False and resumed["paused_at"] is None
    after = pairing.run(store.list_links(user_id=pairing.OWNER))
    assert [row["link_id"] for row in after] == [row["link_id"] for row in before]
    assert after[0]["roots"] == before[0]["roots"]


def test_pause_keeps_the_folder_and_disconnect_still_drops_it() -> None:
    store = pairing.store()
    link_id = _adopted(store)
    pairing.run(store.pause_link(user_id=pairing.OWNER, link_id=link_id, now=pairing._now()))
    listed = pairing.run(store.list_links(user_id=pairing.OWNER))
    assert len(listed[0]["roots"]) == 1, "pausing must not revoke an approved folder"

    assert pairing.run(store.revoke_link(
        user_id=pairing.OWNER, link_id=link_id, now=pairing._now(),
    )) is True
    assert pairing.run(store.list_links(user_id=pairing.OWNER)) == []


def test_a_revoked_link_cannot_be_paused_and_a_foreign_one_is_refused() -> None:
    store = pairing.store()
    link_id = _adopted(store)
    pairing.run(store.revoke_link(user_id=pairing.OWNER, link_id=link_id, now=pairing._now()))
    for name in ("pause_link", "resume_link"):
        try:
            pairing.run(getattr(store, name)(
                user_id=pairing.OWNER, link_id=link_id, now=pairing._now(),
            ))
        except pairing.PcPairingError as refused:
            assert str(refused) == "link not active", name
        else:
            raise AssertionError(f"{name} accepted a revoked link")

    live = _adopted(store, node="node//mesh-pc-07")
    for name in ("pause_link", "resume_link"):
        try:
            pairing.run(getattr(store, name)(
                user_id=pairing.OTHER, link_id=live, now=pairing._now(),
            ))
        except pairing.PcPairingError as refused:
            assert str(refused) == "link not yours", name
        else:
            raise AssertionError(f"{name} let another account move the link")


def test_the_pause_and_resume_routes_take_a_plain_post_and_move_the_card() -> None:
    async def journey():
        store = pairing.store()
        link_id = await _adopt(store)
        app = pairing.app_with(store)
        async with pairing.client(app) as session:
            paused = await session.post(f"/api/pc/pairings/{link_id}/pause")
            listed = await session.get("/api/pc/pairings")
            resumed = await session.post(f"/api/pc/pairings/{link_id}/resume")
        return paused.status_code, paused.json(), listed.json(), resumed.status_code

    paused_status, paused_body, listed, resumed_status = pairing.run(journey())
    assert paused_status == 200, paused_body
    assert paused_body["link"]["paused"] is True
    assert [row["paused"] for row in listed["links"]] == [True]
    assert resumed_status == 200


def test_another_accounts_pause_attempt_is_403_and_an_unknown_link_is_404() -> None:
    async def journey():
        store = pairing.store()
        link_id = await _adopt(store)
        app = pairing.app_with(store)
        async with pairing.client(app, user_id=pairing.OTHER) as stranger:
            foreign_pause = await stranger.post(f"/api/pc/pairings/{link_id}/pause")
            foreign_resume = await stranger.post(f"/api/pc/pairings/{link_id}/resume")
        async with pairing.client(app) as owner:
            unknown = await owner.post("/api/pc/pairings/pclink_" + "f" * 32 + "/pause")
        return (
            foreign_pause.json()["error"]["code"],
            foreign_pause.status_code,
            foreign_resume.status_code,
            unknown.status_code,
        )

    code, pause_status, resume_status, unknown_status = pairing.run(journey())
    assert (code, pause_status, resume_status) == ("pc_pairing_link_forbidden", 403, 403)
    assert unknown_status == 404


def test_a_paused_link_stays_on_the_card_as_paused_and_resumes() -> None:
    """The listing is the owner's inventory, not the dispatch queue.

    A stopped PC must still be visible with its folders, with the resume control
    next to it; only the execution reads drop it.
    """
    async def journey():
        store = pairing.store()
        link_id = await _adopt(store)
        app = pairing.app_with(store)
        async with pairing.client(app) as session:
            await session.post(f"/api/pc/pairings/{link_id}/pause")
            while_paused = await session.get("/api/pc/pairings")
            resumed = await session.post(f"/api/pc/pairings/{link_id}/resume")
            after = await session.get("/api/pc/pairings")
        return while_paused.json(), resumed.json(), after.json()

    while_paused, resumed, after = pairing.run(journey())
    listed = while_paused["links"]
    assert len(listed) == 1, "a paused link must not vanish from the card"
    assert listed[0]["state"] == "paused" and listed[0]["paused"] is True
    assert len(listed[0]["roots"]) == 1, "and it must not lose its folder"
    assert resumed["link"]["state"] == "active" and resumed["link"]["paused"] is False
    assert after["links"][0]["state"] == "active"


def test_a_paused_pc_still_counts_as_a_linked_pc_for_the_desktop_card() -> None:
    """#5951's judge asks "does this account have a PC", not "may we send work"."""
    from app.claw_local_access_routes import _owner_has_linked_pc

    async def journey():
        store = pairing.store()
        link_id = await _adopt(store)
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(pc_device_pairing_store=store)
            )
        )
        before = await _owner_has_linked_pc(request, pairing.OWNER)
        await store.pause_link(user_id=pairing.OWNER, link_id=link_id, now=pairing._now())
        paused = await _owner_has_linked_pc(request, pairing.OWNER)
        await store.revoke_link(user_id=pairing.OWNER, link_id=link_id, now=pairing._now())
        revoked = await _owner_has_linked_pc(request, pairing.OWNER)
        return before, paused, revoked

    before, paused, revoked = pairing.run(journey())
    assert (before, paused, revoked) == (True, True, False)


def test_the_two_routes_are_registered_and_ask_for_no_confirmation_value() -> None:
    app = pairing.app_with(pairing.store())
    methods_by_path: dict[str, list[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        if path in {PC_PAIRING_PAUSE_PATH, PC_PAIRING_RESUME_PATH}:
            methods_by_path[path] = sorted(getattr(route, "methods", None) or ())
    assert methods_by_path == {
        PC_PAIRING_PAUSE_PATH: ["POST"],
        PC_PAIRING_RESUME_PATH: ["POST"],
    }
