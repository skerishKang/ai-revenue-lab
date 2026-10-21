"""#5441 — the lost-password reset mail reuses the existing mail credential.

The reset mail is the only proof of email ownership the flow accepts, so the
credential behind it is a security surface. This file pins how that credential
is located and reused:

* **one credential, one source.** The reset mail and the existing owner-side
  signup-notification channel read the *same* resolved value, so a deployment
  never has to mint a second mail key for the reset flow.
* **reuse first.** The already provisioned owner-side channel binding name wins
  over the reset-specific name, and the account Secrets Store — where every
  other credential of this account lives — is a valid home for the same value.
* **never a crash, never a fake success.** A Secrets Store slot is an async
  ``.get()`` capability rather than a string, and an unreadable binding must
  degrade to "this channel is not configured" instead of breaking the Worker or
  reporting a delivery that never happened.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx

from app.password_reset_delivery import (
    RESET_MAIL_SUBJECT,
    ResendEmailDelivery,
    build_email_delivery,
)
from app.worker_config import (
    MAIL_API_KEY_BINDING_NAMES,
    MAIL_FROM_BINDING_NAMES,
    resolve_first_secret_binding,
)

ROOT = Path(__file__).resolve().parents[1]
API_KEY = "re_" + "A" * 32
OTHER_API_KEY = "re_" + "B" * 32
SENDER = "padiem@example.test"
RECIPIENT = "member@example.test"


class StoreSlot:
    """A Cloudflare Secrets Store binding: an async ``.get()`` capability."""

    def __init__(self, value: str):
        self.value = value
        self.reads = 0

    async def get(self):
        self.reads += 1
        return self.value


class Unreadable:
    """A binding that is neither a string nor resolvable."""

    def __getattr__(self, name):
        raise RuntimeError("this binding cannot be read")


def _resolve(env, names):
    return asyncio.run(resolve_first_secret_binding(env, names))


def test_the_existing_channel_credential_is_reused_from_a_worker_secret():
    env = {"B66_ALERT_RESEND_API_KEY": API_KEY}
    assert _resolve(env, MAIL_API_KEY_BINDING_NAMES) == API_KEY


def test_the_account_secrets_store_slot_is_reused():
    """The Secrets Store is a real home for a PADIEM credential."""
    slot = StoreSlot(API_KEY)
    env = {"PADIEM_RESEND_API_KEY": slot}
    assert _resolve(env, MAIL_API_KEY_BINDING_NAMES) == API_KEY
    assert slot.reads == 1


def test_the_reuse_order_prefers_the_existing_channel_credential():
    """The already provisioned credential wins; no second issuance is implied."""
    env = {
        "B66_ALERT_RESEND_API_KEY": API_KEY,
        "PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY": OTHER_API_KEY,
        "PADIEM_RESEND_API_KEY": OTHER_API_KEY,
    }
    assert _resolve(env, MAIL_API_KEY_BINDING_NAMES) == API_KEY
    assert MAIL_API_KEY_BINDING_NAMES.index("B66_ALERT_RESEND_API_KEY") < (
        MAIL_API_KEY_BINDING_NAMES.index("PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY")
    )


def test_the_sender_address_is_reused_the_same_way():
    env = {"B66_ALERT_EMAIL_FROM": SENDER}
    assert _resolve(env, MAIL_FROM_BINDING_NAMES) == SENDER
    store = StoreSlot(SENDER)
    assert _resolve({"PADIEM_RESEND_EMAIL_FROM": store}, MAIL_FROM_BINDING_NAMES) == SENDER


def test_an_unreadable_binding_never_raises_and_resolves_to_nothing():
    """A broken binding must not take the Worker down with it."""
    env = {"B66_ALERT_RESEND_API_KEY": Unreadable()}
    assert _resolve(env, MAIL_API_KEY_BINDING_NAMES) is None
    assert _resolve({}, MAIL_API_KEY_BINDING_NAMES) is None
    assert _resolve({"B66_ALERT_RESEND_API_KEY": ""}, MAIL_API_KEY_BINDING_NAMES) is None


def test_the_delivery_is_built_from_the_resolved_credential():
    delivery = build_email_delivery(
        resend_api_key=API_KEY, email_from=SENDER
    )
    assert isinstance(delivery, ResendEmailDelivery)
    assert delivery._email_from == SENDER
    assert delivery._api_key == API_KEY


def test_no_credential_means_no_delivery_and_no_fake_success():
    """Unconfigured is an honest 'cannot send', never a silent success."""
    assert build_email_delivery(resend_api_key="", email_from=SENDER) is None
    assert build_email_delivery(resend_api_key=API_KEY, email_from="") is None
    assert build_email_delivery(resend_api_key="not-a-provider-key",
                                email_from=SENDER) is None


def test_the_reset_mail_uses_the_provider_http_contract():
    """The mail is one Resend API call with the Bearer credential."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"id": "probe"})

    delivery = ResendEmailDelivery(
        api_key=API_KEY,
        email_from=SENDER,
        http_transport=httpx.MockTransport(handler),
    )
    sent = asyncio.run(
        delivery.send(to=RECIPIENT, subject=RESET_MAIL_SUBJECT, text="probe body")
    )
    assert sent is True
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer " + API_KEY
    body = str(captured["body"])
    assert '"to":["%s"]' % RECIPIENT in body.replace(" ", "")
    assert SENDER in body
    assert API_KEY not in body


def test_the_worker_shares_one_resolved_credential_with_both_mail_surfaces():
    """One resolution, one value: the reset mail and the signup notifier.

    The composition is pinned at the source level because booting the whole
    Worker needs the real binding surface. The assertion is the contract: the
    credential is resolved once, and the same two variables reach both
    consumers, so a second credential can never be introduced here.
    """
    source = (ROOT / "worker.py").read_text(encoding="utf-8")
    assert source.count("await resolve_first_secret_binding(") == 2
    assert "resend_api_key=mail_api_key" in source
    assert "email_from=mail_from" in source
    assert re.search(
        r"resend_api_key=mail_api_key,\s*\n\s*email_from=mail_from,", source
    ) is not None
    # The raw binding read of the mail credential is gone: a Secrets Store slot
    # is not a string and would break the Worker at composition time.
    assert 'binding_value(self.env, "B66_ALERT_RESEND_API_KEY")' not in source
    assert 'binding_value(self.env, "PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY")' not in source
