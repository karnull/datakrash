"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for the notifiers and how they map to contact addresses
"""

import smtplib
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from deadman_switch import notifier
from deadman_switch.config import ConfigError, ContactConfig
from deadman_switch.notifier import NotifyFailed
from deadman_switch.notifier import smtp as smtp_module
from deadman_switch.notifier.smtp import Smtp
from deadman_switch.notifier.twilio import Twilio

SMTP = {
    "provider": "smtp",
    "host": "smtp.example.com",
    "sender": "me@example.com",
    "username": "me",
    "password": "pw",
}
TWILIO = {
    "provider": "twilio",
    "account_sid": "AC123",
    "token": "tw-token",
    "sender": "+15550000000",
}


def _contact(email="", phone=""):
    return ContactConfig(
        "Test Contact", email, phone, Path("/tmp/message.txt"), "Subject", ()
    )


class FakeSmtp:
    sent = []
    fail = False

    def __init__(self, host, port, timeout):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        pass

    def login(self, username, password):
        if FakeSmtp.fail:
            raise smtplib.SMTPAuthenticationError(535, b"no")

    def send_message(self, message):
        FakeSmtp.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.sent = []
    FakeSmtp.fail = False
    monkeypatch.setattr(smtp_module.smtplib, "SMTP", FakeSmtp)
    return FakeSmtp


def test_smtp_sends_the_message(fake_smtp):
    Smtp("email", SMTP).send("contact@example.com", "Subject", "Body")

    [message] = fake_smtp.sent
    assert message["To"] == "contact@example.com"
    assert message.get_content().strip() == "Body"


def test_smtp_failure_raises(fake_smtp):
    fake_smtp.fail = True
    with pytest.raises(NotifyFailed):
        Smtp("email", SMTP).send("contact@example.com", "Subject", "Body")


def test_twilio_posts_the_message():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["form"] = parse_qs(request.content.decode())
        return httpx.Response(201, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    Twilio("sms", TWILIO, http=http).send("+15551234567", "Subject", "Body")

    assert seen["url"].endswith("/Accounts/AC123/Messages.json")
    assert seen["form"] == {
        "From": ["+15550000000"],
        "To": ["+15551234567"],
        "Body": ["Body"],
    }


def test_twilio_rejection_raises():
    http = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(401))
    )
    with pytest.raises(NotifyFailed, match="401"):
        Twilio("sms", TWILIO, http=http).send("+15551234567", "Subject", "Body")


def test_builds_by_provider():
    built = notifier.build({"email": SMTP, "sms": TWILIO})
    assert isinstance(built["email"], Smtp)
    assert isinstance(built["sms"], Twilio)


def test_unknown_provider_is_a_config_error():
    with pytest.raises(ConfigError):
        notifier.build({"sms": {"provider": "pager"}})


def test_routes_every_address_set():
    built = notifier.build({"email": SMTP, "sms": TWILIO})
    pairs = notifier.routes(
        _contact(email="contact@example.com", phone="+15551234567"), built
    )
    assert [(n.channel, address) for n, address in pairs] == [
        ("email", "contact@example.com"),
        ("sms", "+15551234567"),
    ]


def test_phone_without_sms_notifier_is_a_config_error():
    built = notifier.build({"email": SMTP})
    with pytest.raises(ConfigError, match="contact.phone"):
        notifier.routes(_contact(phone="+15551234567"), built)
