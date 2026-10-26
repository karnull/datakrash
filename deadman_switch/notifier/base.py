"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Base class every contact notifier implements
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import httpx

HTTP_TIMEOUT = 30


class NotifyFailed(Exception):
    pass


class Notifier(ABC):
    # which contact field this notifier delivers to: "email" or "phone"
    address_field: ClassVar[str]

    def __init__(
        self, channel: str, settings: dict[str, Any], http: httpx.Client | None = None
    ):
        self.channel = channel
        self.settings = settings
        self.http = http or httpx.Client(timeout=HTTP_TIMEOUT)

    def setting(self, key: str) -> Any:
        value = self.settings.get(key)
        if value is None or value == "":
            raise NotifyFailed(f"notifier.{self.channel}.{key} is not set")
        return value

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Deliver the message or raise NotifyFailed."""
