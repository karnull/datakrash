"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for a full run of the switch, on a fake clock
"""

from datetime import timedelta
from pathlib import Path

import pytest

from datakrash import password
from datakrash.challenge import Challenger
from datakrash.config import ChallengeConfig, ContactConfig, parse_duration
from datakrash.state import ARMED, FIRED, SPENT, StateStore
from datakrash.watch import EXIT_FAILED, EXIT_OK, EXIT_TEMPFAIL, Watch
from tests.fakes import FakeClock, FakeNtfy, FakeService, RecordingNotifier, failing

SCHEDULE = tuple(
    parse_duration(text)
    for text in ("0h", "1h30m", "3h", "1d", "2d", "3d", "4d", "5d", "6d")
)
SETTINGS = ChallengeConfig(
    server="https://ntfy.example.com",
    topic="prompt",
    reply_topic="reply",
    token="ntfy-token",
    password_file=Path("/tmp/password.hash"),
    reply_window=timedelta(hours=1),
    attempts=3,
)
HASH = password.hash_password("correct horse")


class Rig:
    def __init__(self, tmp_path, services, notifiers=None):
        message = tmp_path / "message.txt"
        message.write_text("Sealed words for the contact.")
        self.clock = FakeClock()
        self.ntfy = FakeNtfy(self.clock)
        self.store = StateStore(tmp_path / "state.json")
        self.email = RecordingNotifier("email", "email")
        self.sms = RecordingNotifier("sms", "phone")
        notifiers = notifiers or [self.email, self.sms]
        addresses = {"email": "contact@example.com", "phone": "+15551234567"}
        contact = ContactConfig(
            "Test Contact",
            addresses["email"],
            addresses["phone"],
            message,
            "Subject",
            SCHEDULE,
        )
        self.watch = Watch(
            services=services,
            routes=[(n, addresses[n.address_field]) for n in notifiers],
            contact=contact,
            challenger=Challenger(SETTINGS, self.ntfy, HASH, self.clock),
            store=self.store,
            clock=self.clock,
        )

    def run(self):
        return self.watch.run()

    def state(self):
        return self.store.load()


def test_activity_ends_the_run(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [True]), FakeService("garmin", [False])])

    assert rig.run() == EXIT_OK
    assert rig.watch.services[1].calls == 0
    assert rig.ntfy.published == []
    assert rig.state().phase == ARMED
    assert rig.state().last_outcome == "activity"


def test_activity_on_a_later_service_counts(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False]), FakeService("garmin", [True])])

    assert rig.run() == EXIT_OK
    assert rig.state().phase == ARMED


def test_failed_service_sends_a_notice_and_moves_on(tmp_path):
    rig = Rig(tmp_path, [failing("github"), FakeService("garmin", [True])])

    assert rig.run() == EXIT_OK
    assert rig.ntfy.published[0][2] == "The github check failed to connect."


def test_silence_then_password_stands_down(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    rig.ntfy.reply_at(rig.clock.now() + timedelta(minutes=10), "correct horse")

    assert rig.run() == EXIT_OK
    assert rig.state().phase == ARMED
    assert rig.email.sent == [] and rig.sms.sent == []


def test_every_service_failing_still_challenges(tmp_path):
    rig = Rig(tmp_path, [failing("github"), failing("garmin")])
    rig.ntfy.reply_at(rig.clock.now() + timedelta(minutes=10), "correct horse")

    assert rig.run() == EXIT_OK
    assert "Proof of life required" in rig.ntfy.titles()


def test_ntfy_down_exits_for_retry_without_firing(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    rig.ntfy.down = True

    assert rig.run() == EXIT_TEMPFAIL
    assert rig.state().challenge.attempt == 1
    assert rig.email.sent == []


def test_full_schedule_reaches_the_contact_nine_times(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    start = rig.clock.now()

    assert rig.run() == EXIT_OK

    assert len(rig.email.sent) == 9 and len(rig.sms.sent) == 9
    state = rig.state()
    assert state.phase == SPENT
    fired_at = state.fired_at
    assert fired_at - start == timedelta(hours=3)
    assert [send.due - fired_at for send in state.sends] == list(SCHEDULE)
    assert "Datakrash fired" in rig.ntfy.titles()


def test_spent_switch_does_not_repeat(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    rig.run()
    rig.clock.advance(days=1)

    assert rig.run() == EXIT_OK
    assert len(rig.email.sent) == 9
    assert rig.state().last_outcome == "spent"


def test_activity_after_spent_rearms(tmp_path):
    github = FakeService("github", [False])
    rig = Rig(tmp_path, [github])
    rig.run()
    github.results = [True]

    rig.run()
    assert rig.state().phase == ARMED


def test_activity_on_day_two_cancels_the_rest(tmp_path):
    github = FakeService("github", [False])
    rig = Rig(tmp_path, [github])

    real_check = github.check_activity

    def check(since):
        fired_at = rig.state().fired_at
        if fired_at and rig.clock.now() >= fired_at + timedelta(days=2):
            return True
        return real_check(since)

    github.check_activity = check
    assert rig.run() == EXIT_OK

    assert len(rig.email.sent) == 4
    assert rig.state().phase == ARMED
    assert rig.state().last_outcome == "stood down: activity"


def test_password_during_the_schedule_cancels_the_rest(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    fired_at = rig.clock.now() + timedelta(hours=3)
    rig.ntfy.reply_at(fired_at + timedelta(hours=2), "correct horse")

    assert rig.run() == EXIT_OK
    assert len(rig.email.sent) == 2
    assert rig.state().last_outcome == "stood down: password confirmed"


def test_partial_failure_resends_only_the_failed_channel(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    rig.sms.fail_times = 1

    assert rig.run() == EXIT_FAILED
    assert (len(rig.email.sent), len(rig.sms.sent)) == (1, 0)
    assert rig.state().phase == FIRED

    rig.clock.advance(minutes=5)
    assert rig.run() == EXIT_OK
    assert (len(rig.email.sent), len(rig.sms.sent)) == (9, 9)


def test_restart_mid_schedule_skips_sends_already_made(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    original_sleep = rig.clock.sleep

    def interrupted_sleep(seconds):
        if rig.state().phase == FIRED and len(rig.email.sent) == 3:
            raise KeyboardInterrupt
        original_sleep(seconds)

    rig.clock.sleep = interrupted_sleep
    with pytest.raises(KeyboardInterrupt):
        rig.run()
    assert len(rig.email.sent) == 3

    rig.clock.sleep = original_sleep
    assert rig.run() == EXIT_OK
    assert len(rig.email.sent) == 9


def test_long_outage_collapses_overdue_sends(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [False])])

    def outage(seconds):
        if rig.state().phase == FIRED and len(rig.email.sent) == 1:
            raise KeyboardInterrupt
        rig.clock.current += timedelta(seconds=seconds)

    rig.clock.sleep = outage
    with pytest.raises(KeyboardInterrupt):
        rig.run()

    rig.clock.sleep = lambda seconds: setattr(
        rig.clock, "current", rig.clock.current + timedelta(seconds=seconds)
    )
    rig.clock.advance(days=2, hours=1)
    assert rig.run() == EXIT_OK

    state = rig.state()
    assert len(rig.email.sent) == 1 + 1 + 4
    assert [send.skipped for send in state.sends] == [
        False,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]


def test_contact_message_never_reaches_the_logs(tmp_path, caplog):
    rig = Rig(tmp_path, [FakeService("github", [False])])
    caplog.set_level("DEBUG")

    rig.run()

    assert "Sealed words" not in caplog.text
    assert "contact@example.com" not in caplog.text
    assert "+15551234567" not in caplog.text


def test_corrupt_state_is_moved_aside(tmp_path):
    rig = Rig(tmp_path, [FakeService("github", [True])])
    (tmp_path / "state.json").write_text("{not json")

    assert rig.run() == EXIT_OK
    assert any(
        path.name.startswith("state.json.corrupt-") for path in tmp_path.iterdir()
    )
    assert rig.state().phase == ARMED
