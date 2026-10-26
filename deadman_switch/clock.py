"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Wall clock in UTC, replaced by a fake one in tests
"""

from __future__ import annotations

import time
from datetime import datetime, timezone


class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(max(seconds, 0))
