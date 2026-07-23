"""Modal deployment import smoke (modal mocked; no deployment performed)."""

from __future__ import annotations

import sys
import types

from app.production import modal_app


def test_modal_module_imports_without_sdk():
    # Importing the module must not require the modal SDK (lazy import).
    assert modal_app.APP_NAME == "ai-revenue-living-learning-staging"
    assert modal_app.SECRET_NAME == "living-learning-staging-secrets"
    assert modal_app.MIN_CONTAINERS == 0  # scale-to-zero
    assert "LL_MIGRATION_DATABASE_URL" not in modal_app.REQUIRED_SECRET_KEYS
    assert "LL_DATABASE_URL" in modal_app.REQUIRED_SECRET_KEYS


def test_build_asgi_app_reuses_factory():
    # The ASGI app is the real FastAPI factory (no separate product behavior).
    from fastapi import FastAPI

    app = modal_app.build_asgi_app()
    assert isinstance(app, FastAPI)


def test_build_app_with_mocked_modal():
    # build_app constructs a Modal App using the SDK; mock the SDK surface.
    modal = types.ModuleType("modal")

    class _Image:
        @staticmethod
        def debian_slim(v):
            return _Image()

        def pip_install(self, *a, **k):
            return self

        def add_local_dir(self, *a, **k):
            return self

    class _Secret:
        @staticmethod
        def from_name(name, required_keys=None):
            return ("secret", name, tuple(required_keys or ()))

    class _App:
        def __init__(self, name, image=None, secrets=None):
            self.name = name
            self.image = image
            self.secrets = secrets
            self.functions = []

        def function(self, *a, **k):
            def deco(fn):
                self.functions.append(fn)
                return fn
            return deco

    class _asgi_app:
        def __call__(self, fn):
            return fn

    modal.Image = _Image
    modal.Secret = _Secret
    modal.App = _App
    modal.asgi_app = _asgi_app

    saved = sys.modules.get("modal")
    sys.modules["modal"] = modal
    try:
        app = modal_app.build_app()
        assert app.name == "ai-revenue-living-learning-staging"
        # The named secret references the documented required keys.
        assert app.secrets[0][1] == "living-learning-staging-secrets"
        assert "LL_DATABASE_URL" in app.secrets[0][2]
        assert app.functions  # the web() ASGI function was registered
    finally:
        if saved is None:
            sys.modules.pop("modal", None)
        else:
            sys.modules["modal"] = saved
