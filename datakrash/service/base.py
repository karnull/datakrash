"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Base class every activity service implements
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

import httpx

HTTP_TIMEOUT = 30


class CheckFailed(Exception):
    """The service could not be asked, which is neither activity nor silence."""


class Service(ABC):
    def __init__(
        self, name: str, settings: dict[str, Any], http: httpx.Client | None = None
    ):
        self.name = name
        self.settings = settings
        self.duration: timedelta = settings["duration"]
        self.http = http or httpx.Client(timeout=HTTP_TIMEOUT)

    def setting(self, key: str) -> Any:
        value = self.settings.get(key)
        if value is None or value == "":
            raise CheckFailed(f"service.{self.name}.{key} is not set")
        return value

    @abstractmethod
    def check_activity(self, since: datetime) -> bool:
        """True if there was activity at or after `since` (UTC), False if none."""
