"""Synthetic world fixture for Living Fiction tests.

The canonical world definition now lives in ``app.preview_data`` so that
production runtime code never imports from ``tests/**``. This module is a thin
re-export shim kept so existing tests continue to import the world from
``tests.fixtures.synthetic_world``.

Working title: "The City That Loses an Hour"
All names are project-created placeholders.
"""

from app.preview_data import WORLD_ID, WORLD_STATE, WORLD_VERSION

__all__ = ["WORLD_ID", "WORLD_STATE", "WORLD_VERSION"]
