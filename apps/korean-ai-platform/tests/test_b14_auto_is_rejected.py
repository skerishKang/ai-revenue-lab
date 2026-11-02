"""2026-11-02 owner decision: ``b14/auto`` was deleted, not paused.

A request that names it is an unknown model exactly like any other
unregistered id. No separate guidance or deprecation response keeps it alive.
"""

from __future__ import annotations


def test_b14_auto_is_rejected_as_an_unknown_model(client) -> None:
    response = client.post(
        "/api/pilot/router/resolve",
        json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_model"
