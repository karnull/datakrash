"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Activity from a GitHub user's event feed
"""

from __future__ import annotations

from datetime import datetime

import httpx

from datakrash.service.base import CheckFailed, Service

API = "https://api.github.com"


class GitHub(Service):
    """Public events by default; with a token for the same user, private ones too."""

    def check_activity(self, since: datetime) -> bool:
        username = self.setting("username")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.get("token"):
            headers["Authorization"] = f"Bearer {self.settings['token']}"

        try:
            response = self.http.get(
                f"{API}/users/{username}/events",
                params={"per_page": 100},
                headers=headers,
            )
            response.raise_for_status()
            events = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CheckFailed(f"GitHub: {type(exc).__name__}: {exc}") from exc

        try:
            return any(
                datetime.fromisoformat(event["created_at"]) >= since for event in events
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckFailed(
                f"GitHub returned an event without a usable created_at: {exc}"
            ) from exc
