"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for the password, the ntfy client and the challenge
"""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from deadman_switch import password
from deadman_switch.challenge import Challenger
from deadman_switch.config import ChallengeConfig
from deadman_switch.ntfy import Ntfy, NtfyError
from deadman_switch.state import Challenge
from tests.fakes import FakeClock, FakeNtfy

HASH = password.hash_password("correct horse")
SETTINGS = ChallengeConfig(
    server="https://ntfy.example.com",
    topic="prompt",
    reply_topic="reply",
    token="ntfy-token",
    password_file=Path("/tmp/password.hash"),
    reply_window=timedelta(hours=1),
    attempts=3,
)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ntfy(clock):
    return FakeNtfy(clock)


def _challenger(clock, ntfy):
    return Challenger(SETTINGS, ntfy, HASH, clock)


def _run(challenger, challenge=None):
    challenge = challenge or Challenge()
    saves = []
    result = challenger.run(challenge, lambda: saves.append(challenge.attempt))
    return result, challenge


# ==============================================================================
# Password


def test_password_round_trip():
    assert password.verify("correct horse", HASH)
    assert not password.verify("wrong horse", HASH)
    assert "correct horse" not in HASH


def test_garbage_hash_never_verifies():
    assert not password.verify("anything", "not-a-hash")


def test_password_file_is_private(tmp_path):
    path = tmp_path / "password.hash"
    password.write(path, "correct horse")

    assert path.stat().st_mode & 0o777 == 0o600
    assert password.verify("correct horse", password.read(path))


def test_missing_password_file_is_an_error(tmp_path):
    with pytest.raises(password.PasswordError):
        password.read(tmp_path / "missing")


# ==============================================================================
# ntfy client


def test_ntfy_publish_sends_token_and_title():
    seen = {}

    def handler(request):
        seen.update(
            url=str(request.url),
            auth=request.headers["authorization"],
            title=request.headers["title"],
        )
        return httpx.Response(200, json={})

    client = Ntfy(
        "https://ntfy.example.com/",
        "ntfy-token",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.publish("prompt", "hello", title="Hi")

    assert seen == {
        "url": "https://ntfy.example.com/prompt",
        "auth": "Bearer ntfy-token",
        "title": "Hi",
    }


def test_ntfy_poll_keeps_messages_only():
    body = "\n".join(
        [
            '{"id":"a","time":1761480000,"event":"open"}',
            '{"id":"b","time":1761480001,"event":"message","message":"pw"}',
        ]
    )
    http = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    )

    [message] = Ntfy("https://ntfy.example.com", "t", http=http).poll(
        "reply", "1761480000"
    )
    assert (message.id, message.text) == ("b", "pw")


def test_ntfy_connection_error_raises():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(NtfyError):
        Ntfy(
            "https://ntfy.example.com",
            "t",
            http=httpx.Client(transport=httpx.MockTransport(refuse)),
        ).poll("r", "0")


# ==============================================================================
# Challenge


def test_correct_on_first_attempt(clock, ntfy):
    ntfy.reply_at(clock.now() + timedelta(minutes=5), "correct horse")

    confirmed, challenge = _run(_challenger(clock, ntfy))

    assert confirmed
    assert challenge.attempt == 1
    assert ntfy.titles() == ["Proof of life required", "Proof of life accepted"]


def test_correct_on_third_attempt(clock, ntfy):
    ntfy.reply_at(clock.now() + timedelta(minutes=1), "wrong")
    ntfy.reply_at(clock.now() + timedelta(minutes=2), "also wrong")
    ntfy.reply_at(clock.now() + timedelta(minutes=3), "correct horse")

    confirmed, challenge = _run(_challenger(clock, ntfy))

    assert confirmed
    assert challenge.attempt == 3


def test_three_wrong_passwords_fail(clock, ntfy):
    for minute in (1, 2, 3):
        ntfy.reply_at(clock.now() + timedelta(minutes=minute), "wrong")

    confirmed, challenge = _run(_challenger(clock, ntfy))

    assert not confirmed
    assert ntfy.titles().count("Proof of life required") == 3


def test_three_silent_windows_fail(clock, ntfy):
    start = clock.now()
    confirmed, _ = _run(_challenger(clock, ntfy))

    assert not confirmed
    assert clock.now() - start == timedelta(hours=3)


def test_silence_then_correct(clock, ntfy):
    ntfy.reply_at(clock.now() + timedelta(hours=1, minutes=10), "correct horse")

    confirmed, challenge = _run(_challenger(clock, ntfy))

    assert confirmed
    assert challenge.attempt == 2


def test_replies_before_the_prompt_are_ignored(clock, ntfy):
    ntfy.reply_at(clock.now() - timedelta(hours=2), "correct horse")

    confirmed, _ = _run(_challenger(clock, ntfy))

    assert not confirmed


def test_resumes_after_restart_with_attempts_kept(clock, ntfy):
    challenge = Challenge(
        attempt=3,
        prompt_at=clock.now() - timedelta(minutes=30),
        cursor=str(int(clock.now().timestamp())),
    )

    confirmed, challenge = _run(_challenger(clock, ntfy), challenge)

    assert not confirmed
    assert ntfy.titles() == []
    assert clock.slept == timedelta(minutes=30)


def test_ntfy_down_uses_no_attempt(clock, ntfy):
    challenger = _challenger(clock, ntfy)
    challenge = Challenge()

    ntfy.down = True
    with pytest.raises(NtfyError):
        challenger.run(challenge, lambda: None)
    assert challenge.attempt == 1

    ntfy.down = False
    clock.advance(minutes=5)
    ntfy.reply_at(clock.now() + timedelta(minutes=1), "correct horse")
    assert challenger.run(challenge, lambda: None)
    assert challenge.attempt == 1


def test_ntfy_dropping_mid_wait_reprompts_same_attempt(clock, ntfy):
    challenger = _challenger(clock, ntfy)
    challenge = Challenge()
    original_poll = ntfy.poll

    def drop(topic, since):
        ntfy.down = True
        return original_poll(topic, since)

    ntfy.poll = drop
    with pytest.raises(NtfyError):
        challenger.run(challenge, lambda: None)
    assert challenge.interrupted

    ntfy.poll = original_poll
    ntfy.down = False
    ntfy.reply_at(clock.now() + timedelta(minutes=1), "correct horse")
    assert challenger.run(challenge, lambda: None)
    assert ntfy.titles().count("Proof of life required") == 2
    assert challenge.attempt == 1
