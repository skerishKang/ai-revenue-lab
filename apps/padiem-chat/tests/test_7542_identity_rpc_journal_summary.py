"""#7542 stage 0: the journal summary adds up identity RPC counts, never journal text.

``tools/identity_rpc_journal_summary.py`` reads the per-minute
``identity_rpc_minute`` lines a Chat journal carries and sums them by RPC and
by day. Every test here feeds it a made-up journal: the script itself reaches
no host, and its report may hold declared RPC names, dates and counts only.
"""
import ast
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import timedelta

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'tools/identity_rpc_journal_summary.py'
SPEC = importlib.util.spec_from_file_location('identity_rpc_journal_summary', SCRIPT)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)

METHODS = frozenset({'resolve_auth_session', 'create_tenant', 'resolve_product_user_for_subject'})
# Shaped like real identifiers on purpose.
PRIVATE = 'sess_private_value_not_for_output'
PRIVATE_SUBJECT = 'sub_0123456789abcdef0123456789abcdef'
PRIVATE_KIND = 'private_kind_label'
HOST = 'journal-host-name-not-for-output'
# The exact line the Chat-side test pins for the same three counts.
EMITTED = ('identity_rpc_minute call.create_tenant:unavailable=1 '
           'call.resolve_auth_session:ok=2,unauthorized=1 '
           'keepwarm.resolve_product_user_for_subject:answered=1')


def iso(stamp: str, message: str) -> str:
    """One ``journalctl -o short-iso`` line."""
    return f'{stamp} {HOST} chat-unit[4242]: {message}'


def json_line(micros: int, message: str, **extra) -> str:
    """One ``journalctl -o json`` line."""
    return json.dumps({'__REALTIME_TIMESTAMP': str(micros), 'MESSAGE': message,
                       '_HOSTNAME': HOST, **extra})


def day(report: dict, name: str) -> dict:
    return next(row for row in report['days'] if row['day'] == name)


def test_rpc_names_come_from_the_adapter_source_without_importing_it(tmp_path):
    source = tmp_path / 'adapter.py'
    source.write_text(
        "raise RuntimeError('must not import')\n"
        "class Adapter:\n"
        "    async def a(self):\n"
        "        await self._rpc('resolve_auth_session', {}, 'session')\n"
        "        await self._rpc_envelope('revoke_all_auth_sessions', {})\n"
        "        getattr(self._binding, 'resolve_active_memberships', None)\n"
        "        await self._rpc_envelope(method_name, payload)\n"
        "        getattr(other, 'not_a_binding_read', None)\n"
        "        await self._rpc('Not A Name', {}, 'x')\n",
        encoding='utf-8')
    assert summary.declared_rpc_methods(source) == {
        'resolve_auth_session', 'revoke_all_auth_sessions', 'resolve_active_memberships'}
    assert summary.declared_rpc_methods(tmp_path / 'missing.py') == frozenset()
    real = summary.declared_rpc_methods()
    assert {'resolve_auth_session', 'resolve_connector_owner_scope', 'establish_auth_session',
            'resolve_product_user_for_subject', 'resolve_active_memberships'} <= real
    assert all(re.fullmatch(r'[a-z][a-z0-9_]+', name) for name in real)


def test_account_read_names_come_from_the_literal_companion_without_importing_it(tmp_path):
    source = tmp_path / 'adapter.py'
    source.write_text("raise RuntimeError('must not import')\n", encoding='utf-8')
    companion = source.with_name('connector_account_shadow.py')
    companion.write_text(
        "raise RuntimeError('must not import')\n"
        "ACCOUNT_READS = {\n"
        "  'workspace': ('resolve_connector_workspace_for_subject', 'workspace'),\n"
        "  'context': ('resolve_connector_context_for_subject', 'context'),\n"
        "  'malformed': ('Not A Name', 'x'),\n"
        "  'dynamic': (method_from_runtime, 'x'),\n"
        "  'incomplete': ('not_a_dispatch_entry',),\n"
        "}\n"
        "UNRELATED = {'x': ('not_a_declared_rpc', 'x')}\n",
        encoding='utf-8')
    assert summary.declared_rpc_methods(source) == {
        'resolve_connector_workspace_for_subject', 'resolve_connector_context_for_subject'}
    companion.write_text('not valid Python :', encoding='utf-8')
    assert summary.declared_rpc_methods(source) == frozenset()


def test_the_emitted_line_is_summed_by_rpc_kind_and_day():
    report = summary.summarize(
        [iso('2026-11-12T09:00:00+0900', EMITTED),
         iso('2026-11-12T09:01:00+0900', EMITTED),
         iso('2026-11-13T00:00:30+0900', 'identity_rpc_minute call.resolve_auth_session:ok=5'),
         iso('2026-11-13T00:01:30+0900', 'identity_rpc_minute empty')],
        methods=METHODS)
    assert [row['day'] for row in report['days']] == ['2026-11-12', '2026-11-13']
    assert day(report, '2026-11-12') == {
        'day': '2026-11-12', 'minute_lines': 2,
        'counts': {
            'call': {'create_tenant': {'unavailable': 2},
                     'resolve_auth_session': {'ok': 4, 'unauthorized': 2}},
            'keepwarm': {'resolve_product_user_for_subject': {'answered': 2}},
        }}
    assert day(report, '2026-11-13') == {
        'day': '2026-11-13', 'minute_lines': 2,
        'counts': {'call': {'resolve_auth_session': {'ok': 5}}}}
    assert (report['schema'], report['utc_offset']) == ('identity-rpc-journal-summary-v1', '+09:00')
    assert (report['input_lines'], report['minute_lines'], report['malformed_lines'],
            report['labels_not_declared']) == (4, 4, 0, 0)


def test_every_dated_journal_format_lands_on_the_same_day_and_the_offset_decides_it():
    # 2026-11-11 15:00:30 UTC is 2026-11-12 00:00:30 at +09:00.
    micros = 1_794_409_230_000_000
    assert summary._EPOCH + timedelta(microseconds=micros) == summary._iso_moment('2026-11-11T15:00:30Z')
    message = 'identity_rpc_minute call.resolve_auth_session:ok=1'
    lines = [
        iso('2026-11-12T00:00:30+0900', message),
        iso('2026-11-12T00:00:30.123456+09:00', message),
        iso('2026-11-11T15:00:30Z', message),
        iso('2026-11-11T10:00:30-05:00', message),
        json_line(micros, message),
    ]
    report = summary.summarize(lines, methods=METHODS)
    assert [(row['day'], row['minute_lines']) for row in report['days']] == [('2026-11-12', 5)]
    assert day(report, '2026-11-12')['counts'] == {'call': {'resolve_auth_session': {'ok': 5}}}
    utc = summary.summarize(lines, methods=METHODS, utc_offset=summary.parse_utc_offset('Z'))
    assert [(row['day'], row['minute_lines']) for row in utc['days']] == [('2026-11-11', 5)]
    assert utc['utc_offset'] == '+00:00'


def test_a_line_without_a_readable_date_is_summed_under_undated():
    message = 'identity_rpc_minute call.resolve_auth_session:ok=2'
    report = summary.summarize(
        [message,                                              # journalctl -o cat
         f'Nov 12 17:45:01 {HOST} chat-unit[4242]: {message}',  # default short format
         iso('2026-13-40T25:61:61+0900', message),              # not a date
         json_line(0, message, __REALTIME_TIMESTAMP='soon'),
         iso('2026-11-12T09:00:00+0900', message)],
        methods=METHODS)
    assert [(row['day'], row['minute_lines']) for row in report['days']] == [
        ('2026-11-12', 1), ('undated', 4)]
    assert day(report, 'undated')['counts'] == {'call': {'resolve_auth_session': {'ok': 8}}}


def test_the_wake_up_ping_is_summed_apart_from_calls_of_the_same_name():
    report = summary.summarize(
        [iso('2026-11-12T09:00:00+0900',
             'identity_rpc_minute call.resolve_product_user_for_subject:ok=3,unauthorized=1 '
             'keepwarm.resolve_product_user_for_subject:answered=1,bad_status=1'),
         iso('2026-11-12T09:01:00+0900',
             'identity_rpc_minute keepwarm.resolve_product_user_for_subject:unavailable=1')],
        methods=METHODS)
    counts = day(report, '2026-11-12')['counts']
    assert counts['call'] == {'resolve_product_user_for_subject': {'ok': 3, 'unauthorized': 1}}
    assert counts['keepwarm'] == {'resolve_product_user_for_subject': {
        'answered': 1, 'bad_status': 1, 'unavailable': 1}}
    table = summary.markdown(report)
    assert '| resolve_product_user_for_subject | 4 | 4 |' in table
    assert '| resolve_product_user_for_subject (answered) | 1 | 1 |' in table
    assert '| total | 4 | 4 |' in table


def test_an_rpc_with_no_calls_shows_zero_and_idle_minutes_still_count_as_coverage():
    report = summary.summarize(
        [iso(f'2026-11-12T09:{minute:02d}:00+0900', 'identity_rpc_minute empty')
         for minute in range(60)],
        methods=METHODS)
    assert day(report, '2026-11-12') == {'day': '2026-11-12', 'minute_lines': 60, 'counts': {}}
    table = summary.markdown(report)
    for method in sorted(METHODS):
        assert f'| {method} | 0 | 0 |' in table
    assert '| minute lines | 60 |' in table


def test_labels_outside_the_declared_sets_are_summed_as_other_and_never_echoed():
    report = summary.summarize(
        [iso('2026-11-12T09:00:00+0900',
             f'identity_rpc_minute call.{PRIVATE}:ok=2 call.{PRIVATE_SUBJECT}:ok=1 '
             f'call.resolve_auth_session:{PRIVATE_KIND}=4 sidecar.resolve_auth_session:ok=8 '
             'call.other:other=16 call.resolve_auth_session:ok=32')],
        methods=METHODS)
    assert day(report, '2026-11-12')['counts'] == {
        'call': {'other': {'ok': 3, 'other': 16},
                 'resolve_auth_session': {'ok': 32, 'other': 4}},
        'other': {'resolve_auth_session': {'ok': 8}},
    }
    # Four labels were not declared; the emitter's own "other" is not one of them.
    assert report['labels_not_declared'] == 4
    table = summary.markdown(report)
    assert '| other | 19 | 19 |' in table
    assert 'counts under an undeclared source: 8' in table
    for text in (table, json.dumps(report)):
        assert PRIVATE not in text and PRIVATE_SUBJECT not in text
        assert PRIVATE_KIND not in text and 'sidecar' not in text


@pytest.mark.parametrize('body', [
    f'{PRIVATE}',
    f'call.resolve_auth_session:ok=1 {PRIVATE}',
    'call.resolve_auth_session:ok=one',
    'call.resolve_auth_session:ok=-1',
    'call.resolve_auth_session:ok=1,',
    'call.resolve_auth_session:ok=1  call.create_tenant:ok=1',
    'call.resolve_auth_session ok=1',
    'call.resolve_auth_session:ok=12345678901',
    f'call.resolve_auth_session:ok=1 session_id={PRIVATE}',
    '',
])
def test_a_line_off_the_grammar_is_counted_as_malformed_and_adds_nothing(body):
    report = summary.summarize(
        [iso('2026-11-12T09:00:00+0900', 'identity_rpc_minute ' + body),
         iso('2026-11-12T09:01:00+0900', 'identity_rpc_minute call.resolve_auth_session:ok=1')],
        methods=METHODS)
    assert (report['malformed_lines'], report['minute_lines']) == (1, 1)
    assert day(report, '2026-11-12')['counts'] == {'call': {'resolve_auth_session': {'ok': 1}}}
    for text in (summary.markdown(report), json.dumps(report)):
        assert PRIVATE not in text


def test_other_journal_lines_and_private_values_never_leave_the_report():
    counter = 'identity_rpc_minute call.resolve_auth_session:ok=1'
    lines = [
        iso('2026-11-12T09:00:00+0900', counter),
        iso('2026-11-12T09:00:01+0900', 'identity_cache_minute wrapper.resolve_auth_session:hit=9,miss=9'),
        iso('2026-11-12T09:00:02+0900',
            f'identity_rpc_slow method=resolve_auth_session ms=900 outcome=ok request_id={PRIVATE}'),
        # A mention inside another message is not a counter line.
        iso('2026-11-12T09:00:03+0900', f'audit note="{counter}" by {PRIVATE}'),
        iso('2026-11-12T09:00:04+0900', f'{PRIVATE} {counter}'),
        json_line(1_794_409_230_000_000, f'{PRIVATE} {counter}'),
        json_line(1_794_409_230_000_000, counter, SESSION=PRIVATE, _CMDLINE=PRIVATE_SUBJECT),
        json.dumps({'MESSAGE': [105, 100], '__REALTIME_TIMESTAMP': '1'}),
        json.dumps([counter]),
        '{' + counter,
        PRIVATE,
        '',
    ]
    report = summary.summarize(lines, methods=METHODS)
    assert (report['input_lines'], report['minute_lines'], report['malformed_lines']) == (12, 2, 0)
    assert day(report, '2026-11-12')['counts'] == {'call': {'resolve_auth_session': {'ok': 2}}}
    for text in (summary.markdown(report), json.dumps(report)):
        assert PRIVATE not in text and PRIVATE_SUBJECT not in text and HOST not in text


def test_the_declared_names_must_be_real_names():
    with pytest.raises(ValueError):
        summary.summarize([], methods=frozenset())
    with pytest.raises(ValueError):
        summary.summarize([], methods=frozenset({'resolve_auth_session', PRIVATE.upper()}))


@pytest.mark.parametrize('text, minutes', [
    ('+09:00', 540), ('+0900', 540), ('Z', 0), ('-05:30', -330), ('+14:00', 840)])
def test_the_day_offset_is_read_strictly(text, minutes):
    assert summary.parse_utc_offset(text) == timedelta(minutes=minutes)


@pytest.mark.parametrize('text', ['', '9', '+9', '+25:00', '+09:60', 'KST', '+09:00 ' + PRIVATE])
def test_a_malformed_day_offset_is_refused(text):
    with pytest.raises(ValueError):
        summary.parse_utc_offset(text)


def test_the_command_reads_stdin_or_files_and_only_prints_the_report(tmp_path):
    journal = '\n'.join([
        iso('2026-11-12T09:00:00+0900', EMITTED),
        iso('2026-11-12T09:00:05+0900', f'http_request session={PRIVATE}'),
    ]) + '\n'
    piped = subprocess.run([sys.executable, str(SCRIPT), '--format', 'json'],
                           input=journal, capture_output=True, text=True, check=True)
    report = json.loads(piped.stdout)
    assert day(report, '2026-11-12')['counts']['call']['resolve_auth_session'] == {
        'ok': 2, 'unauthorized': 1}
    assert report['declared_methods'] == sorted(summary.declared_rpc_methods())
    assert piped.stderr == ''

    path = tmp_path / 'journal.txt'
    path.write_text(journal, encoding='utf-8')
    from_file = subprocess.run([sys.executable, str(SCRIPT), str(path), str(path)],
                               capture_output=True, text=True, check=True)
    assert '| resolve_auth_session | 6 | 6 |' in from_file.stdout
    assert '| minute lines | 2 |' in from_file.stdout
    assert PRIVATE not in piped.stdout + from_file.stdout and HOST not in from_file.stdout
    # The journal file is only read.
    assert path.read_text(encoding='utf-8') == journal and list(tmp_path.iterdir()) == [path]

    for bad in (['--utc-offset', 'KST'], [str(tmp_path / 'missing.txt')]):
        refused = subprocess.run([sys.executable, str(SCRIPT), *bad],
                                 input=journal, capture_output=True, text=True)
        assert refused.returncode == 2 and refused.stdout == ''
        assert PRIVATE not in refused.stderr and 'missing.txt' not in refused.stderr


def test_the_script_is_read_only_and_names_no_host_address_or_secret():
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or '').split('.')[0])
    # No process, network, environment or filesystem-walking module.
    assert imported == {'__future__', 'argparse', 'ast', 'collections', 'datetime', 'json',
                        'pathlib', 're', 'sys', 'typing', 'warnings'}
    opens = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'open']
    assert len(opens) == 1 and len(opens[0].args) == 1  # default mode: read
    writers = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not writers & {'write', 'write_text', 'write_bytes', 'unlink', 'mkdir', 'rename',
                          'environ', 'getenv'}
    text = '\n'.join(node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and isinstance(node.value, str))
    assert not re.search(r'://|\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[\w-]+\.(?:net|com|dev|io|kr|local|service)\b',
                         text)
    assert not re.search(r'(?:^|[\s"\'])/(?:opt|var|etc|home|mnt|srv)/|\b[A-Z]:\\', text)
    # Nothing shaped like a key or a digest either.
    assert not re.search(r'[A-Za-z0-9+/=_-]{40,}', text)


def test_the_summary_reads_what_the_running_chat_prints(capsys):
    """Round trip with the Chat-side counter, when this checkout has it."""
    from app import identity_cache_metrics as metrics
    record_rpc = getattr(metrics, 'record_rpc', None)
    if record_rpc is None:
        pytest.skip('the per-minute RPC counter is not in this checkout yet')
    declared = summary.declared_rpc_methods()
    assert declared == set(metrics.RPC_METHODS)
    assert {
        'resolve_connector_owner_scope_for_subject',
        'resolve_connector_enrollment_consent_for_subject_device',
        'resolve_connector_workspace_for_subject',
        'resolve_connector_context_for_subject',
    } <= declared
    assert set(metrics.RPC_SOURCES) == set(summary.SOURCES)
    assert set(metrics.RPC_OUTCOME_KINDS) == set(summary.KINDS)
    metrics._rpc_counts.clear()
    expected: dict = {}
    for number, method in enumerate(sorted(metrics.RPC_METHODS), start=1):
        for kind in summary.CALL_KINDS:
            for _ in range(number):
                record_rpc('call', method, kind)
            expected.setdefault(method, {})[kind] = number
    for kind in summary.KEEPWARM_KINDS:
        record_rpc('keepwarm', 'resolve_product_user_for_subject', kind)
    metrics.flush()
    printed = capsys.readouterr().out.splitlines()
    report = summary.summarize(
        [iso('2026-11-12T09:00:00+0900', line) for line in printed], methods=declared)
    assert (report['minute_lines'], report['malformed_lines'], report['labels_not_declared']) == (1, 0, 0)
    assert day(report, '2026-11-12')['counts'] == {
        'call': expected,
        'keepwarm': {'resolve_product_user_for_subject': {kind: 1 for kind in summary.KEEPWARM_KINDS}},
    }
