"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for the Garmin service, with the Garmin Connect client faked
"""

from datetime import datetime, timedelta, timezone

import pytest

from deadman_switch.service import CheckFailed
from deadman_switch.service.garmin import Garmin

SINCE = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, activities=(), steps=(), error=None):
        self.activities = list(activities)
        self.steps = list(steps)
        self.error = error

    def get_activities(self, start, limit):
        if self.error:
            raise self.error
        return self.activities

    def get_daily_steps(self, start, end):
        return self.steps


def _garmin(monkeypatch, client):
    service = Garmin(
        "garmin",
        {"email": "me@example.com", "password": "x", "duration": timedelta(days=2)},
    )
    monkeypatch.setattr(service, "_client", lambda: client)
    return service


def test_recent_activity_counts(monkeypatch):
    client = FakeClient(activities=[{"startTimeGMT": "2026-10-25 07:15:00"}])
    assert _garmin(monkeypatch, client).check_activity(SINCE) is True


def test_old_activity_and_no_steps_is_silence(monkeypatch):
    client = FakeClient(
        activities=[{"startTimeGMT": "2026-10-20 07:15:00"}],
        steps=[
            {"calendarDate": "2026-10-24", "totalSteps": 0},
            {"calendarDate": "2026-10-25", "totalSteps": None},
        ],
    )
    assert _garmin(monkeypatch, client).check_activity(SINCE) is False


def test_steps_in_window_count(monkeypatch):
    client = FakeClient(steps=[{"calendarDate": "2026-10-25", "totalSteps": 4120}])
    assert _garmin(monkeypatch, client).check_activity(SINCE) is True


def test_steps_before_window_do_not_count(monkeypatch):
    client = FakeClient(steps=[{"calendarDate": "2026-10-23", "totalSteps": 4120}])
    assert _garmin(monkeypatch, client).check_activity(SINCE) is False


def test_library_error_is_a_failed_check(monkeypatch):
    client = FakeClient(error=ConnectionError("Cloudflare says no"))
    with pytest.raises(CheckFailed):
        _garmin(monkeypatch, client).check_activity(SINCE)


def test_malformed_response_is_a_failed_check(monkeypatch):
    client = FakeClient(activities=[{"startTime": "nonsense"}])
    with pytest.raises(CheckFailed):
        _garmin(monkeypatch, client).check_activity(SINCE)
