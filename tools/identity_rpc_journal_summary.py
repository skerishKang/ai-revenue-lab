#!/usr/bin/env python3
"""Sum the per-minute identity RPC counts in a Chat journal by RPC and by day.

Read-only: journal text comes in on stdin (or from files named on the command
line) and one report goes out on stdout. Nothing is fetched, written or run.

    journalctl -u <chat-unit> -o short-iso --since "8 days ago" \\
        | python tools/identity_rpc_journal_summary.py

Only ``identity_rpc_minute`` lines are read (#7542):

    identity_rpc_minute call.<rpc>:<kind>=<n>[,<kind>=<n>] keepwarm.<rpc>:<kind>=<n>
    identity_rpc_minute empty

``call`` is a product request and ``keepwarm`` the synthetic wake-up ping; the
two are summed apart. An RPC name is accepted only when this checkout's
identity adapter declares it, and a result kind only from the fixed list
below. Any other label is added to ``other`` and never echoed; a line that
does not follow the grammar is counted as malformed and otherwise ignored. The
report therefore holds declared names, dates and counts - never journal text.

Days are calendar days at ``--utc-offset`` (default +09:00). Use a journal
output format that carries the date: ``short-iso``, ``short-iso-precise`` or
``json``. Lines without a readable date are summed under ``undated``.

``minute lines`` is how many counter lines a day has - 1440 for one process
that ran all day. A zero beside a full day is a real zero; a zero beside few
lines is a gap in the log.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Iterator
import warnings

SCHEMA = 'identity-rpc-journal-summary-v1'
MARKER = 'identity_rpc_minute '
SOURCES = ('call', 'keepwarm')
CALL_KINDS = ('ok', 'unauthorized', 'forbidden', 'rejected', 'unavailable',
              'invalid', 'interrupted')
KEEPWARM_KINDS = ('answered', 'bad_status', 'unavailable')
KINDS = frozenset(CALL_KINDS) | frozenset(KEEPWARM_KINDS)
OTHER = 'other'
UNDATED = 'undated'
DEFAULT_UTC_OFFSET = timedelta(hours=9)
ADAPTER_SOURCE = (Path(__file__).resolve().parents[1]
                  / 'apps' / 'padiem-chat' / 'app' / 'control_plane_identity_worker.py')

_NAME = re.compile(r'[a-z][a-z0-9_]{0,63}')
_ENTRY = re.compile(
    r'([a-z]{1,16})\.([a-z][a-z0-9_]{0,63}):'
    r'([a-z_]{1,24}=\d{1,9}(?:,[a-z_]{1,24}=\d{1,9})*)')
_ISO_STAMP = re.compile(
    r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:[.,]\d{1,9})?(Z|[+-]\d{2}:?\d{2})')
_OFFSET = re.compile(r'([+-])(\d{2}):?(\d{2})')
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def declared_rpc_methods(source: Path = ADAPTER_SOURCE) -> frozenset[str]:
    """RPC names the identity adapter sends; the source is parsed, never imported."""
    try:
        with warnings.catch_warnings():
            # Parsing must not echo unrelated code-warning text.
            warnings.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, SyntaxError):
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in ('_rpc', '_rpc_envelope'):
            candidate = node.args[0]
        elif (isinstance(function, ast.Name) and function.id == 'getattr' and len(node.args) >= 2
              and isinstance(node.args[0], ast.Attribute) and node.args[0].attr == '_binding'):
            # The one read that reaches the binding without the shared envelope.
            candidate = node.args[1]
        else:
            continue
        if (isinstance(candidate, ast.Constant) and isinstance(candidate.value, str)
                and _NAME.fullmatch(candidate.value)):
            names.add(candidate.value)
    names.update(_account_read_methods(source.with_name('connector_account_shadow.py')))
    return frozenset(names)


def _account_read_methods(source: Path) -> frozenset[str]:
    """The additive client's literal dispatch table, without importing it."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, SyntaxError):
        return frozenset()
    names: set[str] = set()
    for node in tree.body:
        if (not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict)
                or not any(isinstance(target, ast.Name) and target.id == 'ACCOUNT_READS'
                           for target in node.targets)):
            continue
        for value in node.value.values:
            if not isinstance(value, ast.Tuple) or len(value.elts) != 2:
                continue
            candidate = value.elts[0]
            if (isinstance(candidate, ast.Constant) and isinstance(candidate.value, str)
                    and _NAME.fullmatch(candidate.value)):
                names.add(candidate.value)
    return frozenset(names)


def parse_utc_offset(text: str) -> timedelta:
    """``+09:00``, ``+0900`` or ``Z`` as a timedelta."""
    if text == 'Z':
        return timedelta(0)
    match = _OFFSET.fullmatch(text)
    if match is None or int(match[2]) > 14 or int(match[3]) > 59:
        raise ValueError('invalid_utc_offset')
    delta = timedelta(hours=int(match[2]), minutes=int(match[3]))
    return -delta if match[1] == '-' else delta


def _format_offset(offset: timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    sign = '-' if minutes < 0 else '+'
    return f'{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}'


def _iso_moment(line: str) -> datetime | None:
    """The UTC moment of an ISO stamp at the very start of a text journal line."""
    match = _ISO_STAMP.match(line)
    if match is None:
        return None
    try:
        local = datetime(*(int(match[index]) for index in range(1, 7)), tzinfo=timezone.utc)
        return local - parse_utc_offset(match[7])
    except (ValueError, OverflowError):
        return None


def _message(line: str) -> tuple[datetime | None, str] | None:
    """(moment, counter message) of one journal line, or None when it is not one."""
    line = line.rstrip('\r\n')
    if line.startswith('{'):
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if isinstance(record, dict):
            message = record.get('MESSAGE')
            if not isinstance(message, str) or not message.startswith(MARKER):
                return None
            stamp = record.get('__REALTIME_TIMESTAMP')
            moment = None
            if isinstance(stamp, str) and stamp.isdigit() and len(stamp) <= 17:
                try:
                    moment = _EPOCH + timedelta(microseconds=int(stamp))
                except OverflowError:
                    moment = None
            return moment, message
    at = line.find(MARKER)
    # The counter is the whole message: at the line start, or right after the
    # "<host> <unit>[pid]: " prefix. A mention inside another message is not one.
    if at < 0 or (at and line[max(at - 2, 0):at] != ': '):
        return None
    return _iso_moment(line), line[at:]


def _entries(body: str, methods: frozenset[str]) -> tuple[list[tuple[str, str, str, int]], int] | None:
    """([(source, rpc, kind, count)], undeclared labels) or None for a malformed body."""
    if body == 'empty':
        return [], 0
    rows: list[tuple[str, str, str, int]] = []
    undeclared = 0
    for token in body.split(' '):
        entry = _ENTRY.fullmatch(token)
        if entry is None:
            return None
        labels = []
        for label, declared in ((entry[1], SOURCES), (entry[2], methods)):
            if label not in declared:
                undeclared += label != OTHER
                label = OTHER
            labels.append(label)
        for pair in entry[3].split(','):
            kind, _, number = pair.partition('=')
            if kind not in KINDS:
                undeclared += kind != OTHER
                kind = OTHER
            rows.append((labels[0], labels[1], kind, int(number)))
    return rows, undeclared


def summarize(lines: Iterable[str], *, methods: frozenset[str],
              utc_offset: timedelta = DEFAULT_UTC_OFFSET) -> dict:
    if not methods or not all(isinstance(name, str) and _NAME.fullmatch(name) for name in methods):
        raise ValueError('invalid_declared_methods')
    counts: Counter = Counter()
    minute_lines: Counter = Counter()
    input_lines = malformed = undeclared = 0
    for line in lines:
        input_lines += 1
        found = _message(line)
        if found is None:
            continue
        moment, message = found
        parsed = _entries(message[len(MARKER):].strip(), methods)
        if parsed is None:
            malformed += 1
            continue
        day = UNDATED
        if moment is not None:
            try:
                day = (moment + utc_offset).date().isoformat()
            except OverflowError:
                day = UNDATED
        minute_lines[day] += 1
        undeclared += parsed[1]
        for source, method, kind, number in parsed[0]:
            counts[day, source, method, kind] += number
    days = sorted(day for day in minute_lines if day != UNDATED)
    if UNDATED in minute_lines:
        days.append(UNDATED)
    rows = []
    for day in days:
        nested: dict = {}
        for (count_day, source, method, kind), number in sorted(counts.items()):
            if count_day == day:
                nested.setdefault(source, {}).setdefault(method, {})[kind] = number
        rows.append({'day': day, 'minute_lines': minute_lines[day], 'counts': nested})
    return {
        'schema': SCHEMA,
        'utc_offset': _format_offset(utc_offset),
        'input_lines': input_lines,
        'minute_lines': sum(minute_lines.values()),
        'malformed_lines': malformed,
        'labels_not_declared': undeclared,
        'declared_methods': sorted(methods),
        'days': rows,
    }


def _table(headings: list[str], rows: list[list[object]]) -> list[str]:
    lines = ['| ' + ' | '.join(headings) + ' |',
             '| ' + ' | '.join(['---'] + ['---:'] * (len(headings) - 1)) + ' |']
    lines += ['| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows]
    return lines


def markdown(summary: dict) -> str:
    days = [row['day'] for row in summary['days']]

    def per_day(source: str, method: str | None = None, kind: str | None = None) -> list[int]:
        cells = []
        for row in summary['days']:
            total = 0
            for name, kinds in row['counts'].get(source, {}).items():
                if method is None or name == method:
                    total += sum(number for label, number in kinds.items()
                                 if kind is None or label == kind)
            cells.append(total)
        return cells

    def names(source: str) -> set[str]:
        return {name for row in summary['days'] for name in row['counts'].get(source, {})}

    def kinds_seen(source: str) -> set[str]:
        return {kind for row in summary['days']
                for by_kind in row['counts'].get(source, {}).values() for kind in by_kind}

    lines = [
        f"# Identity RPC counts by day (UTC{summary['utc_offset']})",
        '',
        f"input lines {summary['input_lines']} · minute lines {summary['minute_lines']} · "
        f"malformed lines {summary['malformed_lines']} · "
        f"labels not declared in this checkout {summary['labels_not_declared']}",
        '',
        '## Calls by RPC and day (wake-up ping excluded)',
        '',
    ]
    methods = list(summary['declared_methods'])
    if OTHER in names('call'):
        methods.append(OTHER)
    rows = []
    for method in methods:
        cells = per_day('call', method)
        rows.append([method, *cells, sum(cells)])
    totals = per_day('call')
    rows.append(['total', *totals, sum(totals)])
    lines += _table(['RPC', *days, 'total'], rows)

    call_kinds = list(CALL_KINDS) + sorted(kinds_seen('call') - set(CALL_KINDS))
    rows = []
    for method in methods:
        cells = [sum(per_day('call', method, kind)) for kind in call_kinds]
        rows.append([method, *cells, sum(cells)])
    lines += ['', '## Calls by RPC and result kind (whole period)', '']
    lines += _table(['RPC', *call_kinds, 'total'], rows)

    lines += ['', '## Wake-up ping by day', '']
    ping_kinds = list(KEEPWARM_KINDS) + sorted(kinds_seen('keepwarm') - set(KEEPWARM_KINDS))
    rows = []
    for method in sorted(names('keepwarm')):
        for kind in ping_kinds:
            cells = per_day('keepwarm', method, kind)
            rows.append([f'{method} ({kind})', *cells, sum(cells)])
    lines += _table(['RPC (result kind)', *days, 'total'], rows)

    lines += ['', '## Minute lines by day', '']
    lines += _table(['', *days], [['minute lines', *(row['minute_lines'] for row in summary['days'])]])
    unsourced = sum(per_day(OTHER))
    if unsourced:
        lines += ['', f'counts under an undeclared source: {unsourced}']
    return '\n'.join(lines)


def _input_lines(paths: list[str]) -> Iterator[str]:
    if not paths:
        reconfigure = getattr(sys.stdin, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(errors='replace')
        yield from sys.stdin
        return
    for path in paths:
        with open(path, encoding='utf-8', errors='replace') as handle:
            yield from handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Sum identity_rpc_minute journal lines by RPC and by day (read-only).')
    parser.add_argument('paths', nargs='*', help='journal text files; stdin when omitted')
    parser.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    parser.add_argument('--utc-offset', default='+09:00',
                        help='offset that decides which day a line belongs to (default +09:00)')
    args = parser.parse_args(argv)
    try:
        utc_offset = parse_utc_offset(args.utc_offset)
    except ValueError:
        parser.error('--utc-offset must look like +09:00')
    methods = declared_rpc_methods()
    if not methods:
        parser.error('no identity RPC names are declared in this checkout')
    try:
        summary = summarize(_input_lines(args.paths), methods=methods, utc_offset=utc_offset)
    except OSError:
        parser.error('a journal file could not be read')
    print(markdown(summary) if args.format == 'markdown'
          else json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
