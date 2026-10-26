"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Activity from Garmin Connect: recorded activities and daily steps
"""

from __future__ import annotations

from datetime import datetime, timezone

from deadman_switch.service.base import CheckFailed, Service


class Garmin(Service):
    """Uses the unofficial garminconnect library, as Garmin has no public personal API."""

    def _client(self):
        from garminconnect import Garmin as Client

        client = Client(self.setting("email"), self.setting("password"))
        client.login(self.settings.get("tokens"))
        return client

    def check_activity(self, since: datetime) -> bool:
        today = datetime.now(timezone.utc).date()

        # the library raises its own and requests' exceptions, so anything it throws is a failed check
        try:
            client = self._client()
            activities = client.get_activities(0, 1)
            steps = client.get_daily_steps(since.date().isoformat(), today.isoformat())
            return _recent_activity(activities, since) or _steps_since(steps, since)
        except Exception as exc:
            raise CheckFailed(f"Garmin: {type(exc).__name__}: {exc}") from exc


def _recent_activity(activities, since: datetime) -> bool:
    for activity in activities or []:
        started = datetime.fromisoformat(activity["startTimeGMT"]).replace(
            tzinfo=timezone.utc
        )
        if started >= since:
            return True
    return False


def _steps_since(days, since: datetime) -> bool:
    # steps come per local calendar day, so the day the window opens counts in full
    return any(
        (day.get("totalSteps") or 0) > 0
        and day["calendarDate"] >= since.date().isoformat()
        for day in days or []
    )
