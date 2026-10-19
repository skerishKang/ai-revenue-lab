"""#3580 outbound Telegram trusted-binding tests.

Hermetic: the secret source and the pairing source are local doubles, and the
document transport is the existing fake. No Telegram call, token exchange,
secret store or Production binding is exercised.
"""
from __future__ import annotations

import json
import unittest

import test_telegram_artifact_delivery as tg

from kagent.artifact_delivery_execution_receipt import DeliveryTerminalStatus
from kagent.connector_trust import ConnectorBindingState
from kagent.telegram_artifact_delivery import TelegramArtifactDeliveryAdapter
from kagent.telegram_outbound_binding import (
    CHAT_ID_FROM_REQUEST_BODY, NEW_SECRET_STORE, PRODUCTION_OUTBOUND_BINDING_COMPOSED,
    TOKEN_CACHED, TOKEN_IN_MODEL_CONTEXT, TelegramOutboundBindingError,
    TrustedTelegramOutboundBinding, build_trusted_telegram_outbound_binding,
)

TOKEN = b"123456789:AAoutboundBindingTokenMaterial"
SHORT_TOKEN = b"123456:short"
PROVIDER_CHAT_ID = 987_654_321
GROUP_CHAT_ID = -100_123_456_789


class SecretSource:
    def __init__(self, token=TOKEN, error=None):
        self.token = token
        self.error = error
        self.calls = []

    def resolve_bot_token(self, *, binding_ref, bot_ref):
        self.calls.append((binding_ref, bot_ref))
        if self.error is not None:
            raise self.error
        return self.token


class ChatIdSource:
    def __init__(self, value=PROVIDER_CHAT_ID, error=None):
        self.value = value
        self.error = error
        self.calls = []

    def resolve_provider_chat_id(self, *, binding_ref, bot_ref, chat_ref):
        self.calls.append((binding_ref, bot_ref, chat_ref))
        if self.error is not None:
            raise self.error
        return self.value


def binding(*, secrets=None, chat_ids=None, scope=None):
    return TrustedTelegramOutboundBinding(
        scope=scope if scope is not None else tg._scope(),
        secrets=secrets, chat_ids=chat_ids,
    )


def resolve_token(item, **overrides):
    params = dict(binding_ref=tg.BINDING_REF, bot_ref=tg.BOT_REF)
    params.update(overrides)
    return item.resolve_bot_token(**params)


def resolve_chat(item, **overrides):
    params = dict(binding_ref=tg.BINDING_REF, bot_ref=tg.BOT_REF, chat_ref=tg.CHAT_REF)
    params.update(overrides)
    return item.provider_chat_id(**params)


def adapter(item, *, context=None, send=None):
    return TelegramArtifactDeliveryAdapter(
        scope=tg._scope(),
        trusted_binding=item,
        document_send=send if send is not None else tg._FakeDocumentSend(),
        artifact_material=tg._FakeMaterialResolver(tg._material()),
        channel_context=(lambda: context) if context is not None else (lambda: tg._context()),
        approval_authority=tg._FakeApprovalAuthority(),
        account_ref=tg.ACCOUNT_REF,
        actor_ref=tg.SENDER_REF,
        clock=lambda: tg.NOW,
    )


class TelegramOutboundBindingTests(unittest.TestCase):
    def test_binding_is_scope_bound_and_stores_no_secret(self):
        item = binding()
        projection = item.safe_dict()
        self.assertIs(projection["token_source_configured"], False)
        self.assertIs(projection["chat_id_source_configured"], False)
        self.assertIs(TOKEN_CACHED, False)
        self.assertIs(TOKEN_IN_MODEL_CONTEXT, False)
        self.assertIs(CHAT_ID_FROM_REQUEST_BODY, False)
        self.assertIs(NEW_SECRET_STORE, False)
        self.assertIs(PRODUCTION_OUTBOUND_BINDING_COMPOSED, False)
        self.assertEqual(projection["construction_provider_calls"], 0)
        self.assertIs(projection["production_claim"], False)

    def test_build_returns_none_without_a_trusted_scope(self):
        self.assertIsNone(build_trusted_telegram_outbound_binding())
        self.assertIsNone(build_trusted_telegram_outbound_binding(scope=object()))
        built = build_trusted_telegram_outbound_binding(scope=tg._scope())
        self.assertIsInstance(built, TrustedTelegramOutboundBinding)

    def test_constructor_requires_usable_ports(self):
        with self.assertRaises(TelegramOutboundBindingError):
            binding(secrets=object())
        with self.assertRaises(TelegramOutboundBindingError):
            binding(chat_ids=object())

    def test_unconfigured_sources_refuse(self):
        item = binding()
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_token(item)
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_chat(item)

    def test_resolves_token_and_chat_id_for_the_paired_chat(self):
        secrets, chat_ids = SecretSource(), ChatIdSource()
        item = binding(secrets=secrets, chat_ids=chat_ids)
        self.assertEqual(resolve_token(item), TOKEN)
        self.assertEqual(resolve_chat(item), PROVIDER_CHAT_ID)
        self.assertEqual(secrets.calls, [(tg.BINDING_REF, tg.BOT_REF)])
        self.assertEqual(chat_ids.calls, [(tg.BINDING_REF, tg.BOT_REF, tg.CHAT_REF)])

    def test_negative_group_chat_id_is_valid(self):
        item = binding(secrets=SecretSource(), chat_ids=ChatIdSource(GROUP_CHAT_ID))
        self.assertEqual(resolve_chat(item), GROUP_CHAT_ID)

    def test_foreign_binding_bot_or_chat_is_refused(self):
        secrets, chat_ids = SecretSource(), ChatIdSource()
        item = binding(secrets=secrets, chat_ids=chat_ids)
        for overrides in (
            {"binding_ref": "binding_other"},
            {"bot_ref": "bot_other"},
        ):
            with self.assertRaises(TelegramOutboundBindingError):
                resolve_token(item, **overrides)
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_chat(item, chat_ref="chat_unpaired")
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_chat(item, chat_ref="")
        # Nothing was resolved from a foreign reference.
        self.assertEqual(secrets.calls, [])
        self.assertEqual(chat_ids.calls, [])

    def test_token_and_chat_id_contracts_are_reused(self):
        item = binding(secrets=SecretSource(SHORT_TOKEN), chat_ids=ChatIdSource())
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_token(item)
        bad_ids = binding(secrets=SecretSource(), chat_ids=ChatIdSource(True))
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_chat(bad_ids)
        string_ids = binding(secrets=SecretSource(), chat_ids=ChatIdSource("987"))
        with self.assertRaises(TelegramOutboundBindingError):
            resolve_chat(string_ids)

    def test_source_failure_fails_closed_without_leaking(self):
        item = binding(
            secrets=SecretSource(error=RuntimeError("token=" + TOKEN.decode())),
            chat_ids=ChatIdSource(error=RuntimeError("chat=" + str(PROVIDER_CHAT_ID))),
        )
        with self.assertRaises(TelegramOutboundBindingError) as token_error:
            resolve_token(item)
        self.assertNotIn(TOKEN.decode(), str(token_error.exception))
        with self.assertRaises(TelegramOutboundBindingError) as chat_error:
            resolve_chat(item)
        self.assertNotIn(str(PROVIDER_CHAT_ID), str(chat_error.exception))

    def test_projection_leaks_no_token_or_chat_id(self):
        item = binding(secrets=SecretSource(), chat_ids=ChatIdSource())
        rendered = json.dumps(item.safe_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(TOKEN.decode(), rendered)
        self.assertNotIn(str(PROVIDER_CHAT_ID), rendered)
        self.assertNotIn(str(GROUP_CHAT_ID), rendered)
        self.assertNotIn(tg.CHAT_REF, rendered)

    def test_real_binding_drives_existing_adapter_to_succeeded_receipt(self):
        secrets, chat_ids = SecretSource(), ChatIdSource()
        send = tg._FakeDocumentSend()
        adapter_with_binding = adapter(
            binding(secrets=secrets, chat_ids=chat_ids), send=send
        )
        receipt = adapter_with_binding.deliver(tg._request())
        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.SUCCEEDED)
        self.assertEqual(receipt.external_side_effect_count, 1)
        self.assertEqual(len(send.calls), 1)
        self.assertEqual(send.calls[0]["token"], TOKEN)
        self.assertEqual(send.calls[0]["provider_chat_id"], PROVIDER_CHAT_ID)
        self.assertEqual(len(secrets.calls), 1)
        self.assertEqual(len(chat_ids.calls), 1)

    def test_revoked_binding_refuses_before_the_token_is_resolved(self):
        secrets, chat_ids = SecretSource(), ChatIdSource()
        revoked = tg._binding(
            state=ConnectorBindingState.REVOKED, revoked_at=tg.NOW
        )
        adapter_with_binding = adapter(
            binding(secrets=secrets, chat_ids=chat_ids),
            context=tg._context(binding=revoked),
        )
        with self.assertRaises(Exception):
            adapter_with_binding.deliver(tg._request())
        # The existing channel re-resolution refuses first; the secret source
        # is never consulted for a dead binding.
        self.assertEqual(secrets.calls, [])
        self.assertEqual(chat_ids.calls, [])


if __name__ == "__main__":
    unittest.main()
