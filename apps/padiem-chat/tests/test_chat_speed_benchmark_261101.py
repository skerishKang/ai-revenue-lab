"""The speed experiment uses actual guards and makes its synthetic scope explicit."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / 'scripts/dev/benchmark_chat_requests_261101.py'
SPEC = importlib.util.spec_from_file_location('chat_speed_benchmark', SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.mark.asyncio
@pytest.mark.parametrize('improved', [False, True])
async def test_benchmark_runs_five_authenticated_requests_without_external_io(improved):
    result = await benchmark.scenario(improved=improved, writer_hold_ms=10, identity_delay_ms=1)
    assert result['cache'] is improved
    assert result['read_workers'] == (2 if improved else 0)
    assert result['measured_identity_calls'] == (0 if improved else 5)
    assert result['warmup_identity_calls'] == (1 if improved else 0)
    assert len(result['requests']) == 5
    assert {item['route'] for item in result['requests']} == {route for _, route in benchmark.ROUTES}
    assert all(item['status'] == 200 for item in result['requests'])
    assert all(item['duration_ms'] >= 0 for item in result['requests'])
    assert all(set(item) == {'route', 'status', 'duration_ms', 'timings_ms'} for item in result['requests'])
    output = json.dumps(result)
    assert 'synthetic-benchmark-session' not in output
    assert 'synthetic-benchmark-only-not-a-live-secret' not in output
