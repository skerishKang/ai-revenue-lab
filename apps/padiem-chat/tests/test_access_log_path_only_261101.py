"""Access lines keep the path; a one-time code in the query is never recorded."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from uvicorn.config import LOGGING_CONFIG

from app import local_server
from app.access_log import QueryStrippingFilter, uvicorn_log_config

CODE = 'synthetic-one-time-authorization-code'
STATE = 'synthetic-state-value-not-for-logs'
EMAIL = 'person@example.invalid'
TOKEN = 'synthetic-bearer-marker'
TARGET = f'/auth/shared/callback?code={CODE}&state={STATE}&scope=profile&email={EMAIL}&token={TOKEN}'


def access_record(target=TARGET):
    return logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1,
                             '%s - "%s %s %s" %s',
                             ('203.0.113.7:0', 'GET', target, '1.1', 302), None)


def test_the_query_string_leaves_the_record_entirely():
    record = access_record()
    assert QueryStrippingFilter().filter(record) is True
    line = logging.Formatter('%(message)s').format(record)
    assert all(value not in line for value in (CODE, STATE, EMAIL, TOKEN, 'scope=profile'))
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
    assert all(value not in line for value in (CODE, STATE, EMAIL, TOKEN))
    assert '/auth/shared/callback' in line and '302' in line


def test_chat_host_services_use_the_path_only_launcher():
    root = Path(__file__).resolve().parents[3]
    service_dir = root / 'deploy' / 'host-com2' / 'chat'
    for name, port in (('padiem-chat-com2.service', '8798'), ('padiem-chat-staging.service', '8801')):
        source = (service_dir / name).read_text(encoding='utf-8')
        assert f'-m app.local_server --host 127.0.0.1 --port {port}' in source
        assert '-m uvicorn ' not in source
    launch_examples = (
        root / 'apps' / 'padiem-chat' / 'README.md',
        root / 'apps' / 'padiem-chat' / 'scripts' / 'b62_ui_verify.py',
    )
    for path in launch_examples:
        source = path.read_text(encoding='utf-8')
        assert 'python -m app.local_server' in source
        assert 'python -m uvicorn app.main:app' not in source


def test_cloudflared_examples_use_error_only_request_logging():
    root = Path(__file__).resolve().parents[3]
    examples = (
        root / 'deploy' / 'host-com2' / 'chat' / 'cloudflared-chat-com2.example.yml',
        root / 'deploy' / 'host-com2' / 'b14' / 'cloudflared-config.example.yml',
    )
    for path in examples:
        lines = path.read_text(encoding='utf-8').splitlines()
        assert 'loglevel: error' in lines
        assert 'loglevel: debug' not in lines
