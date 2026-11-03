import base64

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.auth_validation_cache import _sql_timing_operation
from app.d1_sqlite import _log_slow_sql, _sql_operation_label
from app.cpython_shared_login import NativeES256Signer, ReusableHttpxTokenExchange
from app.request_telemetry import _CURRENT_REQUEST_ID
from app.shared_auth_compare_flow import TOKEN_URL
from app.shared_login_timing import (
    begin_login_timings,
    end_login_timings,
    format_login_timing_fields,
)


def _b64int(value):
    return base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode('ascii')


def _jwk():
    private = ec.generate_private_key(ec.SECP256R1()).private_numbers()
    return {
        'kty': 'EC',
        'crv': 'P-256',
        'd': _b64int(private.private_value),
        'x': _b64int(private.public_numbers.x),
        'y': _b64int(private.public_numbers.y),
    }


@pytest.mark.asyncio
async def test_native_signer_reuses_key_and_refreshes_after_in_place_rotation(monkeypatch):
    signer = NativeES256Signer()
    jwk = _jwk()
    signer.prepare(jwk)
    real_derive = ec.derive_private_key
    derived = []

    def count_derivations(*args, **kwargs):
        derived.append(True)
        return real_derive(*args, **kwargs)

    monkeypatch.setattr(ec, 'derive_private_key', count_derivations)
    first = await signer.sign(jwk, b'callback-assertion-1')
    second = await signer.sign(jwk, b'callback-assertion-2')
    assert len(derived) == 0

    rotated = _jwk()
    jwk.update(rotated)
    signature = await signer.sign(jwk, b'callback-assertion-3')
    assert len(derived) == 1
    public = real_derive(int.from_bytes(
        base64.urlsafe_b64decode(jwk['d'] + '=' * (-len(jwk['d']) % 4)), 'big'
    ), ec.SECP256R1()).public_key()
    public.verify(
        encode_dss_signature(int.from_bytes(signature[:32], 'big'),
                             int.from_bytes(signature[32:], 'big')),
        b'callback-assertion-3',
        ec.ECDSA(hashes.SHA256()),
    )
    assert len(first) == len(second) == len(signature) == 64


@pytest.mark.asyncio
async def test_reusable_exchange_reuses_client_and_records_only_safe_timing():
    requests = []
    clients = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={'access_token': 'synthetic-access'},
            headers={'server-timing': 'auth_client;dur=2.25, auth_code;dur=3.50, auth_sign;dur=0.75, auth_total;dur=8.00'},
        )

    def make_client():
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False)
        clients.append(client)
        return client

    exchange = ReusableHttpxTokenExchange(client_factory=make_client)
    token, stats = begin_login_timings()
    request_token = _CURRENT_REQUEST_ID.set('synthetic-request-42')
    try:
        first = await exchange(TOKEN_URL, {'code': 'synthetic-code'})
        second = await exchange(TOKEN_URL, {'code': 'synthetic-code-2'})
        fields = format_login_timing_fields(stats)
    finally:
        _CURRENT_REQUEST_ID.reset(request_token)
        end_login_timings(token)
        await exchange.aclose()

    assert first == second == {'access_token': 'synthetic-access'}
    assert len(clients) == 1 and clients[0].is_closed
    assert len(requests) == 2
    assert all(request.headers['x-request-id'] == 'synthetic-request-42' for request in requests)
    assert all(request.headers['user-agent'].startswith('PADIEM-Chat/1.0') for request in requests)
    values = dict(item.split('=', 1) for item in fields)
    assert values['exchange_headers_n'] == '2'
    assert values['exchange_body_n'] == '2'
    assert values['exchange_total_n'] == '2'
    assert values['portal_code_exchange_ms'] == '7'
    assert values['portal_total_ms'] == '16'
    assert all('synthetic-code' not in item and 'synthetic-access' not in item for item in fields)


@pytest.mark.asyncio
async def test_default_exchange_pool_uses_keepalive_and_closes(monkeypatch):
    from app import cpython_shared_login

    constructed = []
    real_client = cpython_shared_login.httpx.AsyncClient

    def build_client(**kwargs):
        constructed.append(kwargs)
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, json={'access_token': 'synthetic-access'}))
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(cpython_shared_login.httpx, 'AsyncClient', build_client)
    exchange = ReusableHttpxTokenExchange()
    try:
        result = await exchange(TOKEN_URL, {'code': 'synthetic-code'})
    finally:
        await exchange.aclose()

    assert result == {'access_token': 'synthetic-access'}
    assert len(constructed) == 1
    assert constructed[0]['limits'].keepalive_expiry == 75.0
    assert constructed[0]['follow_redirects'] is False


def test_slow_sql_log_separates_reader_setup_without_query_values(capsys):
    token = _CURRENT_REQUEST_ID.set('synthetic-sql-request')
    try:
        _log_slow_sql(
            "SELECT product_user_id FROM auth_validation_cache WHERE owner_id='private-value'",
            1052.0,
            query_ms=1.0,
            reader_setup_ms=1051.0,
        )
    finally:
        _CURRENT_REQUEST_ID.reset(token)

    line = capsys.readouterr().out.strip()
    assert line == (
        'sqlite_slow_execute request_id=synthetic-sql-request '
        'operation=select_auth_validation_cache duration_ms=1052 query_ms=1 reader_setup_ms=1051'
    )
    assert 'private-value' not in line


def test_auth_cache_sql_timing_uses_fixed_operation_names():
    assert _sql_timing_operation(
        'SELECT product_user_id FROM auth_validation_cache WHERE kind=? AND owner_id=?'
    ) == 'session_read'
    assert _sql_timing_operation(
        'SELECT product_user_id FROM auth_account_link_cache WHERE owner_id=?'
    ) == 'link_read'
    assert _sql_timing_operation(
        'SELECT revision FROM auth_validation_cache_revision WHERE id=1'
    ) == 'revision_read'
    assert _sql_timing_operation('SELECT * FROM users WHERE id=?') is None
    assert _sql_operation_label('SELECT product_user_id FROM auth_validation_cache WHERE owner_id=?') == 'select_auth_validation_cache'
    assert _sql_operation_label('UPDATE users SET display_name=? WHERE id=?') == 'update_users'
    assert _sql_operation_label('SELECT ?') == 'select'
