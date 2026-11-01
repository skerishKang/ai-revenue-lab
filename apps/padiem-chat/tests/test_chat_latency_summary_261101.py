"""The log report may contain aggregate route timing, never request material."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'scripts/ops/summarize_chat_latency_261101.py'
SPEC = importlib.util.spec_from_file_location('chat_latency_summary_261101', SCRIPT)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)
ROUTE = '/api/claw/inbox/{kind}'


def event(duration=10, **kwargs):
    return json.dumps({'event': 'http_request', 'service': 'padiem-chat', 'route': ROUTE,
                       'status': 200, 'duration_ms': duration, **kwargs})


def test_route_registry_uses_literals_and_imported_constants_without_importing_app(tmp_path):
    (tmp_path / 'paths.py').write_text("ROOT = '/api/claw'\nDEVICES = ROOT + '/devices'\n")
    (tmp_path / 'routes.py').write_text(
        "from .paths import DEVICES as PATH\nraise RuntimeError('must not import')\n"
        "routes = [Route(PATH, handler), Route('/api/items/{item_id}', handler), Route(dynamic, handler)]\n")
    assert summary.declared_routes(tmp_path) == {'/api/claw/devices', '/api/items/{item_id}'}
    real = summary.declared_routes()
    assert {ROUTE, '/api/claw/local-access/devices', '/api/auth/status', '/health'} <= real
    assert '/api/claw/inbox/private-kind' not in real


def test_percentiles_stage_means_and_missing_measurements():
    lines = [event(i, timings_ms={'auth': i / 2}) for i in range(1, 21)]
    lines += [event(200)]
    report = summary.summarize(lines, routes=frozenset({ROUTE}))
    row = report['top'][0]
    assert report['accepted_requests'] == 21
    assert row['total_ms'] == {'mean': 19.524, 'max': 200.0, 'p95': 20.0}
    assert row['stages_ms']['auth'] == {'mean': 5.25, 'samples': 20}
    assert row['stages_ms']['sqlite_wait'] == {'mean': None, 'samples': 0}
    assert 'unmeasured' in summary.markdown(report)


def test_legacy_event_does_not_turn_unmeasured_stages_into_zero():
    row = summary.summarize([event()], routes=frozenset({ROUTE}))['top'][0]
    assert all(value == {'mean': None, 'samples': 0} for value in row['stages_ms'].values())


def test_private_values_and_unknown_routes_never_leave_report():
    private = 'private-token-body-user-query-not-for-output'
    lines = [event(10, request_id=private, body=private, headers={'authorization': private},
                   timings_ms={'auth': 2, private: 123}),
             event(500, route=ROUTE + '?' + private),
             event(500, route='/api/claw/inbox/' + private),
             event(500, route=private), private,
             event(500, service=private)]
    report = summary.summarize(lines, routes=frozenset({ROUTE}))
    assert report['accepted_requests'] == 1 and report['ignored_lines'] == 5
    assert private not in json.dumps(report) + summary.markdown(report)
    assert set(report['top'][0]['stages_ms']) == set(summary.STAGES)


@pytest.mark.parametrize('duration', [True, None, '5', -1, float('nan'), float('inf')])
def test_invalid_total_duration_is_ignored(duration):
    report = summary.summarize([event(duration)], routes=frozenset({ROUTE}))
    assert report['accepted_requests'] == 0 and report['top'] == []


def test_status_and_invalid_stages_are_not_arbitrary_log_fields():
    lines = [event(status='private-status'), event(status=True), event(status=600),
             event(12, status=503, timings_ms={'auth': -1, 'queue': 'private', 'b14': float('nan')}),
             event(20, status=200, timings_ms={'auth': 0})]
    report = summary.summarize(lines, routes=frozenset({ROUTE}))
    row = report['top'][0]
    assert row['requests'] == 2 and row['status_counts'] == {'200': 1, '503': 1}
    assert row['stages_ms']['auth'] == {'mean': 0.0, 'samples': 1}
    assert row['stages_ms']['b14']['mean'] is None
    table = summary.markdown(report)
    assert '| Status counts |' in table and '| 200:1,503:1 |' in table


def test_mixed_journal_prefix_json_message_and_top_sort():
    second = '/api/auth/status'
    lines = ['prefix: ' + event(30), json.dumps({'MESSAGE': event(50)}),
             event(70, route=second), 'unrelated log', '{}']
    report = summary.summarize(lines, routes=frozenset({ROUTE, second}), top=1)
    assert report['accepted_requests'] == 3 and len(report['top']) == 1
    assert report['top'][0]['route'] == second
    with pytest.raises(ValueError, match='invalid_summary_options'):
        summary.summarize([], routes=frozenset(), top=0)


def test_cli_emits_parseable_summary_from_stdin_without_product_dependencies():
    process = subprocess.run([sys.executable, '-I', str(SCRIPT), '--top', '5'],
                             input=event(13), text=True, capture_output=True, check=True)
    result = json.loads(process.stdout)
    assert result['top'][0]['route'] == ROUTE
    assert result['top'][0]['stages_ms']['auth']['mean'] is None
    assert process.stderr == ''
