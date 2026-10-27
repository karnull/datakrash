"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Stands in for a real notifier during drills, so nothing reaches the contact
"""

from __future__ import annotations

import logging

from datakrash.notifier.base import Notifier

LOG = logging.getLogger(__name__)


class Printer(Notifier):
    def __init__(self, channel: str, address_field: str):
        self.channel = channel
        self.address_field = address_field
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject))
        LOG.info(
            "would message the contact via %s: %r, %d characters",
            self.channel,
            subject,
            len(body),
        )
