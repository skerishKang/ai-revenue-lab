#!/usr/bin/env python3
"""Summarize existing Chat request logs without printing request material.

Read ``journalctl -u padiem-chat-com2 -o cat`` output on stdin. Route labels are
accepted only when they are declared by the checkout's Python ``Route`` calls;
concrete request paths, query strings and unknown labels are never echoed.
Legacy events without stage instrumentation remain unmeasured (JSON null).
Stage durations overlap (for example identity inside auth); do not sum them.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys
import warnings
from typing import Iterable

STAGES = ('auth', 'edge', 'identity', 'p01', 'b14', 'queue',
          'sqlite_wait', 'sqlite_execute')
APP_ROOT = Path(__file__).resolve().parents[2] / 'apps' / 'padiem-chat' / 'app'


def declared_routes(app_root: Path = APP_ROOT) -> frozenset[str]:
    """Read literals and imported string constants; never import product code."""
    modules: dict[str, ast.Module] = {}
    bindings: dict[tuple[str, str], ast.expr | tuple[str, str]] = {}
    for path in app_root.rglob('*.py'):
        relative = path.relative_to(app_root).with_suffix('')
        module = '.'.join(('app', *relative.parts))
        try:
            with warnings.catch_warnings():
                # Source parsing must not echo unrelated code-warning text.
                warnings.simplefilter('ignore', SyntaxWarning)
                tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, SyntaxError):
            continue
        modules[module] = tree
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        bindings[module, target.id] = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value:
                bindings[module, statement.target.id] = statement.value
            elif isinstance(statement, ast.ImportFrom):
                if statement.level:
                    parent = module.split('.')[:-statement.level]
                    source = '.'.join((*parent, *(statement.module or '').split('.'))).rstrip('.')
                else:
                    source = statement.module or ''
                for name in statement.names:
                    bindings[module, name.asname or name.name] = (source, name.name)

    def literal(module: str, node: ast.expr, seen: frozenset = frozenset()) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = literal(module, node.left, seen), literal(module, node.right, seen)
            return left + right if left is not None and right is not None else None
        if isinstance(node, ast.Name):
            key = (module, node.id)
            if key in seen:
                return None
            value = bindings.get(key)
            if isinstance(value, tuple):
                return literal(value[0], ast.Name(id=value[1]), seen | {key})
            if isinstance(value, ast.expr):
                return literal(module, value, seen | {key})
        return None

    routes = set()
    for module, tree in modules.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', None)
            if name != 'Route':
                continue
            path_node = node.args[0] if node.args else next(
                (keyword.value for keyword in node.keywords if keyword.arg == 'path'), None)
            path = literal(module, path_node) if path_node is not None else None
            if path and path.startswith('/') and not any(char in path for char in ('?', '#', '\n', '\r')):
                routes.add(path)
    return frozenset(routes)


def _number(value) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _event(line: str) -> dict | None:
    try:
        value = json.loads(line[line.index('{'):])
        if isinstance(value, dict) and isinstance(value.get('MESSAGE'), str):
            message = value['MESSAGE']
            value = json.loads(message[message.index('{'):])
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


def summarize(lines: Iterable[str], *, routes: frozenset[str], top: int = 5,
              sort: str = 'max') -> dict:
    """Only fixed aggregate fields leave this function; arbitrary metadata dies here."""
    if top < 1 or sort not in {'mean', 'max', 'p95'}:
        raise ValueError('invalid_summary_options')
    buckets = defaultdict(lambda: {'total': [], 'status': Counter(),
                                   'stages': {stage: [] for stage in STAGES}})
    input_lines = 0
    for line in lines:
        input_lines += 1
        event = _event(line)
        if not event or event.get('event') != 'http_request' or event.get('service') != 'padiem-chat':
            continue
        route = event.get('route')
        if not isinstance(route, str) or route not in routes:
            continue
        elapsed = _number(event.get('duration_ms'))
        status = event.get('status')
        if elapsed is None or type(status) is not int or not 100 <= status <= 599:
            continue
        bucket = buckets[route]
        bucket['total'].append(elapsed)
        bucket['status'][status] += 1
        stages = event.get('timings_ms')
        if isinstance(stages, dict):
            for stage in STAGES:
                value = _number(stages.get(stage))
                if value is not None:
                    bucket['stages'][stage].append(value)
    rows = []
    for route, bucket in buckets.items():
        values = sorted(bucket['total'])
        rows.append({
            'route': route,
            'requests': len(values),
            'status_counts': {str(status): count for status, count in sorted(bucket['status'].items())},
            'total_ms': {'mean': round(math.fsum(value / len(values) for value in values), 3),
                         'max': round(values[-1], 3),
                         'p95': round(values[math.ceil(len(values) * .95) - 1], 3)},
            'stages_ms': {stage: {'mean': round(math.fsum(value / len(samples) for value in samples), 3) if samples else None,
                                 'samples': len(samples)}
                          for stage, samples in bucket['stages'].items()},
        })
    rows.sort(key=lambda row: (-row['total_ms'][sort], row['route']))
    accepted = sum(row['requests'] for row in rows)
    return {'schema': 'chat-request-latency-v1', 'input_lines': input_lines,
            'accepted_requests': accepted, 'ignored_lines': input_lines - accepted,
            'sort': sort, 'top': rows[:top]}


def markdown(summary: dict) -> str:
    headings = ('Route', 'N', 'Status counts', 'Mean ms', 'P95 ms', 'Max ms', *STAGES)
    lines = ['| ' + ' | '.join(headings) + ' |',
             '| ' + ' | '.join('---' for _ in headings) + ' |']
    for row in summary['top']:
        stages = [row['stages_ms'][stage]['mean'] for stage in STAGES]
        statuses = ','.join(f'{status}:{count}' for status, count in row['status_counts'].items())
        values = (row['route'], row['requests'], statuses, row['total_ms']['mean'],
                  row['total_ms']['p95'], row['total_ms']['max'], *stages)
        lines.append('| ' + ' | '.join('unmeasured' if value is None else str(value)
                                     for value in values) + ' |')
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top', type=int, default=5)
    parser.add_argument('--sort', choices=('mean', 'p95', 'max'), default='max')
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error('--top must be positive')
    routes = declared_routes()
    if not routes:
        parser.error('no declared Chat routes found in this checkout')
    summary = summarize(sys.stdin, routes=routes, top=args.top, sort=args.sort)
    print(markdown(summary) if args.format == 'markdown' else json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
