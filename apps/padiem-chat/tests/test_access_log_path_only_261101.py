"""Access lines keep the path; a one-time code in the query is never recorded."""
from __future__ import annotations

import logging

import pytest
from uvicorn.config import LOGGING_CONFIG

from app import local_server
from app.access_log import QueryStrippingFilter, uvicorn_log_config

CODE = 'synthetic-one-time-authorization-code'
STATE = 'synthetic-state-value-not-for-logs'
TARGET = f'/auth/shared/callback?code={CODE}&state={STATE}&scope=profile'


def access_record(target=TARGET):
    return logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1,
                             '%s - "%s %s %s" %s',
                             ('203.0.113.7:0', 'GET', target, '1.1', 302), None)


def test_the_query_string_leaves_the_record_entirely():
    record = access_record()
    assert QueryStrippingFilter().filter(record) is True
    line = logging.Formatter('%(message)s').format(record)
    assert CODE not in line and STATE not in line and 'scope=profile' not in line
    assert '/auth/shared/callback' in line and '302' in line and '203.0.113.7' in line


@pytest.mark.parametrize('target', ['/health', '/api/claw/inbox', '/'])
def test_a_request_without_a_query_is_left_alone(target):
    record = access_record(target)
    QueryStrippingFilter().filter(record)
    assert record.args[2] == target


def test_the_launcher_hands_the_filter_to_uvicorn(monkeypatch):
    calls = []
    import uvicorn
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: calls.append(kwargs))
    assert local_server.main(['--host', '127.0.0.1', '--port', '8798']) == 0
    config = calls[0]['log_config']
    assert config['handlers']['access']['filters'] == ['padiem_path_only']
    assert isinstance(config['filters']['padiem_path_only']['()'](), QueryStrippingFilter)
    assert config is not LOGGING_CONFIG
    assert 'filters' not in LOGGING_CONFIG['handlers']['access']


def test_the_real_access_formatter_prints_the_path_only():
    from uvicorn.logging import AccessFormatter
    record = access_record()
    assert QueryStrippingFilter().filter(record) is True
    line = AccessFormatter(
        fmt=LOGGING_CONFIG['formatters']['access']['fmt'], use_colors=False).format(record)
    assert CODE not in line and STATE not in line
    assert '/auth/shared/callback' in line and '302' in line
