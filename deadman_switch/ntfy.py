"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Publishes to and polls ntfy topics
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

HTTP_TIMEOUT = 30


class NtfyError(Exception):
    """ntfy could not be reached, so nothing can be concluded about a reply."""


@dataclass(frozen=True)
class Message:
    id: str
    time: datetime
    text: str


class Ntfy:
    def __init__(self, server: str, token: str, http: httpx.Client | None = None):
        self.server = server.rstrip("/")
        self.http = http or httpx.Client(timeout=HTTP_TIMEOUT)
        self.headers = {"Authorization": f"Bearer {token}"}

    def publish(
        self,
        topic: str,
        message: str,
        *,
        title: str = "",
        priority: str = "default",
        tags: str = "",
    ) -> None:
        headers = {**self.headers, "Priority": priority}
        if title:
            headers["Title"] = title
        if tags:
            headers["Tags"] = tags

        try:
            response = self.http.post(
                f"{self.server}/{topic}", content=message.encode(), headers=headers
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NtfyError(
                f"cannot publish to ntfy: {type(exc).__name__}: {exc}"
            ) from exc

    def poll(self, topic: str, since: str) -> list[Message]:
        """Messages after `since`, a unix timestamp or a message id, oldest first."""

        try:
            response = self.http.get(
                f"{self.server}/{topic}/json",
                params={"poll": "1", "since": since},
                headers=self.headers,
            )
            response.raise_for_status()
            events = [
                json.loads(line) for line in response.text.splitlines() if line.strip()
            ]
            return [
                Message(
                    id=event["id"],
                    time=datetime.fromtimestamp(event["time"], timezone.utc),
                    text=event.get("message", ""),
                )
                for event in events
                if event.get("event") == "message"
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise NtfyError(f"cannot read from ntfy: {type(exc).__name__}") from exc
