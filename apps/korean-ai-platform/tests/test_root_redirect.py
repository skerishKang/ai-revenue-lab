"""Regression coverage for the public Worker root entrypoint."""


def test_root_redirects_to_workspace(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/workspace"


def test_root_redirect_target_renders(client):
    response = client.get("/", follow_redirects=True)

    assert response.status_code == 200
    assert response.url.path == "/workspace"
    assert "ws_chat" in response.text
