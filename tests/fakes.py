"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Fake clock, ntfy server, services and notifiers shared by the tests
"""

from datetime import datetime, timedelta, timezone

from deadman_switch.ntfy import Message, NtfyError
from deadman_switch.service import CheckFailed

START = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=START):
        self.current = now
        self.slept = timedelta(0)

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.current += timedelta(seconds=seconds)
        self.slept += timedelta(seconds=seconds)

    def advance(self, **kwargs):
        self.current += timedelta(**kwargs)


class FakeNtfy:
    """Replies are scheduled ahead; a poll only sees those already published by the fake clock."""

    def __init__(self, clock):
        self.clock = clock
        self.replies = []
        self.published = []
        self.down = False

    def reply_at(self, when, text):
        self.replies.append(
            Message(id=f"m{len(self.replies) + 1}", time=when, text=text)
        )
        self.replies.sort(key=lambda message: message.time)

    def publish(self, topic, message, *, title="", priority="default", tags=""):
        if self.down:
            raise NtfyError("down")
        self.published.append((topic, title, message))

    def poll(self, topic, since):
        if self.down:
            raise NtfyError("down")
        visible = [
            message for message in self.replies if message.time <= self.clock.now()
        ]
        if since.isdigit():
            return [
                message for message in visible if message.time.timestamp() >= int(since)
            ]
        ids = [message.id for message in visible]
        return visible[ids.index(since) + 1 :] if since in ids else visible

    def titles(self):
        return [title for _, title, _ in self.published]


class FakeService:
    def __init__(self, name, results):
        self.name = name
        self.duration = timedelta(days=1)
        self.results = list(results)
        self.calls = 0

    def check_activity(self, since):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


def failing(name):
    return FakeService(name, [CheckFailed(f"{name} unreachable")])


class RecordingNotifier:
    def __init__(self, channel, address_field, fail_times=0):
        self.channel = channel
        self.address_field = address_field
        self.fail_times = fail_times
        self.sent = []

    def send(self, to, subject, body):
        from deadman_switch.notifier import NotifyFailed

        if self.fail_times:
            self.fail_times -= 1
            raise NotifyFailed(f"{self.channel} down")
        self.sent.append(to)
