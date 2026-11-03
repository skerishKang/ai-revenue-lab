"""#6686 — the COM2 CPython host composes the Mesh source like the Worker.

`worker.py` composes ``build_oracle_mesh_return_source_from_env(env)`` and
hands it to ``create_app(oracle_mesh_return_source=...)``. The local CPython
entry had no such wiring, so every verified PC owner's PC-lane turn was
refused with ``mesh_source_unconfigured`` (chat_pc_drive.py:493) and the
whole turn could fail at the Engine admission. These tests pin the host-side
wiring to the same builder the Worker uses.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import local_cpython

_APP_FILE = Path(local_cpython.__file__)


def test_the_host_entry_uses_the_worker_env_builder():
    """The same env→source builder the Worker composes, on the CPython entry."""
    source = _APP_FILE.read_text(encoding="utf-8")
    # The factory is loaded inside uvicorn's running loop; the builder must be
    # awaited from startup, never asyncio.run() at factory time.
    assert "await build_oracle_mesh_return_source_from_env(os.environ)" in source
    assert "app.router.on_startup.append(_compose_oracle_mesh_return_source_on_startup)" in source
    assert "async def _compose_oracle_mesh_return_source_on_startup(app=app):" in source
    # The host cannot await the builder at factory time, but create_app gates the
    # internal Engine lanes on this argument, so the entry hands the mount-time
    # marker (fail-closed until the startup hook composes the real source).
    assert "oracle_mesh_return_source = host_engine_lane_mount_marker(os.environ)" in source
    assert "oracle_mesh_return_source=oracle_mesh_return_source," in source
    assert "oracle_mesh_legacy_map_lane=legacy_map_lane_enabled(os.environ)" in source
    assert "asyncio.run(build_oracle_mesh_return_source_from_env" not in source


def test_an_unconfigured_env_still_leaves_one_explicit_startup_line():
    """A missing binding keeps fail-closed behaviour AND a fixed log marker."""
    source = _APP_FILE.read_text(encoding="utf-8")
    assert "oracle_mesh_source_unconfigured=" in source
    assert "oracle_mesh_return_source=mesh_env_configured" in source


def test_the_worker_root_composes_the_same_builder():
    """No second composition dialect: worker.py and local_cpython.py agree."""
    worker = (Path(local_cpython.__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "build_oracle_mesh_return_source_from_env(self.env)" in worker
    assert "oracle_mesh_return_source=_oracle_mesh_return_source" in worker


def test_the_env_builder_reads_the_published_binding_names():
    """os.environ carries the same names the Worker bindings publish."""
    from app.oracle_mesh_read_return_routes import (
        CONNECTOR_WATCH_READ_SECRET_ENV,
        ORACLE_MESH_CHANNEL_SECRET_ENV,
        ORACLE_MESH_EXECUTION_MODE_ENV,
        ORACLE_MESH_LEGACY_MAP_LANE_ENV,
        ORACLE_MESH_OWNERSHIP_MAP_ENV,
    )
    env = {
        ORACLE_MESH_EXECUTION_MODE_ENV: "off",
        ORACLE_MESH_CHANNEL_SECRET_ENV: "s" * 32,
        # No ownership map is deployed here; the retired lane path composes
        # the source without one, which proves the wiring end to end.
        ORACLE_MESH_LEGACY_MAP_LANE_ENV: "off",
    }
    import asyncio

    from app.oracle_mesh_read_return_routes import build_oracle_mesh_return_source_from_env
    source = asyncio.run(build_oracle_mesh_return_source_from_env(env))
    assert source is not None and source.configured is True

    absent = asyncio.run(build_oracle_mesh_return_source_from_env({}))
    assert absent is None
