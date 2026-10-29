"""#5573 follow-up: the legacy ownership-map lane can be retired without a map.

The map's value lives in a write-only store, so a second map (V2) cannot be authored by
reading the first, and one relative path in production history already carries two
distinct targets. The lane is therefore retired by a switch rather than recreated:

* ``ORACLE_MESH_LEGACY_MAP_LANE=off`` answers a request that names a file for the map with
  a guidance refusal — 409 and a sentence, never "not yours" — before any session or
  identity work;
* the channel source composes **without** the map, so poll/renew/cancel/busy and the
  read-only watch keep working for a deployment that has no map at all;
* absence or any other value keeps today's behaviour, which is also the rollback.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import app.oracle_mesh_read_return_routes as routes


SECRET = "legacy-lane-channel-secret-value-261029"
WATCH = "legacy-lane-watch-secret-value-261029"


def _request(*, lane_enabled: bool):
    state = SimpleNamespace(oracle_mesh_legacy_map_lane=lane_enabled)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _answer(response):
    return response.status_code, json.loads(response.body)


def test_the_switch_reads_off_only_and_defaults_to_today():
    assert routes.legacy_map_lane_enabled({}) is True
    assert routes.legacy_map_lane_enabled({routes.ORACLE_MESH_LEGACY_MAP_LANE_ENV: "on"}) is True
    assert routes.legacy_map_lane_enabled({routes.ORACLE_MESH_LEGACY_MAP_LANE_ENV: "off"}) is False
    assert routes.legacy_map_lane_enabled({routes.ORACLE_MESH_LEGACY_MAP_LANE_ENV: " OFF "}) is False
    assert routes.legacy_map_lane_enabled({routes.ORACLE_MESH_LEGACY_MAP_LANE_ENV: "maybe"}) is True


def test_a_retired_lane_answers_with_guidance_not_a_refusal():
    target, response = asyncio.run(routes.resolve_oracle_mesh_execution(
        _request(lane_enabled=False), path_relative="notes.txt"))
    assert target is None and response is not None
    status, body = _answer(response)
    assert status == 409 and status != 403
    assert body["ok"] is False
    assert body["error"]["code"] == "oracle_mesh_map_lane_retired"
    assert "내 컴퓨터 연결" in body["error"]["message"]


def test_an_enabled_lane_still_takes_the_existing_path():
    # Nothing about the switch may change today's behaviour: with the lane on, the
    # refusal the test above sees must not appear (the call proceeds to identity work,
    # which this bare request cannot satisfy — any outcome but the guidance code passes).
    target, response = asyncio.run(routes.resolve_oracle_mesh_execution(
        _request(lane_enabled=True), path_relative="notes.txt"))
    if response is not None:
        body = json.loads(response.body)
        assert body.get("error", {}).get("code") != "oracle_mesh_map_lane_retired"


def test_the_source_composes_without_a_map_when_the_lane_is_off():
    env = {
        routes.ORACLE_MESH_CHANNEL_SECRET_ENV: SECRET,
        routes.ORACLE_MESH_EXECUTION_MODE_ENV: "mesh",
        routes.ORACLE_MESH_LEGACY_MAP_LANE_ENV: "off",
        routes.CONNECTOR_WATCH_READ_SECRET_ENV: WATCH,
    }
    source = asyncio.run(routes.build_oracle_mesh_return_source_from_env(env))
    assert source is not None and source.configured is True
    # The retired map authorizes nobody, and the channel/watch secrets are untouched.
    assert source.classify(account_ref="usr_" + "a" * 32, path_relative="notes.txt") == "none"
    assert source.target_for(account_ref="usr_" + "a" * 32,
                             path_relative="notes.txt") is None
    assert source.command_target(account_ref="usr_" + "a" * 32) is None
    assert source.check_channel_secret(SECRET) is True
    assert source.check_read_secret(WATCH) is True


def test_a_missing_map_is_still_fatal_when_the_lane_is_on():
    env = {
        routes.ORACLE_MESH_CHANNEL_SECRET_ENV: SECRET,
        routes.ORACLE_MESH_EXECUTION_MODE_ENV: "mesh",
    }
    assert asyncio.run(routes.build_oracle_mesh_return_source_from_env(env)) is None
