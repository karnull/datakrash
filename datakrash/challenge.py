"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Asks the owner for their password over ntfy, with a limited number of attempts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from datakrash import password
from datakrash.clock import Clock
from datakrash.config import ChallengeConfig, format_duration
from datakrash.ntfy import Message, Ntfy, NtfyError
from datakrash.state import Challenge

LOG = logging.getLogger(__name__)

POLL_SECONDS = 15


@dataclass
class Challenger:
    settings: ChallengeConfig
    ntfy: Ntfy
    password_hash: str
    clock: Clock
    label: str = ""

    def run(self, challenge: Challenge, save: Callable[[], None]) -> bool:
        """True once the right password arrives, False when every attempt is used up."""

        while challenge.attempt <= self.settings.attempts:
            if challenge.prompt_at is None or challenge.interrupted:
                self._prompt(challenge)
                save()

            reply = self._await_reply(challenge, save)
            if reply is not None and self.is_password(reply.text):
                LOG.info(
                    "Correct password on attempt %d of %d",
                    challenge.attempt,
                    self.settings.attempts,
                )
                self.notice(
                    "Confirmed. Stand down until the next check.",
                    title="Proof of life accepted",
                )
                return True

            LOG.warning(
                "Attempt %d of %d failed: %s",
                challenge.attempt,
                self.settings.attempts,
                "wrong password" if reply else "no reply",
            )
            challenge.attempt += 1
            challenge.prompt_at = None
            save()

        return False

    def is_password(self, text: str) -> bool:
        return password.verify(text.strip(), self.password_hash)

    def notice(self, message: str, *, title: str = "Datakrash") -> None:
        """Informational push to the owner; a failure here is logged, never fatal."""

        try:
            self.ntfy.publish(self.settings.topic, self.label + message, title=title)
        except NtfyError as exc:
            LOG.warning("Could not send notice to ntfy: %s", exc)

    def _prompt(self, challenge: Challenge) -> None:
        sent_at = self.clock.now()
        self.ntfy.publish(
            self.settings.topic,
            f"{self.label}No activity seen. Reply with your password on {self.settings.reply_topic}. "
            f"Attempt {challenge.attempt} of {self.settings.attempts}; {format_duration(self.settings.reply_window)} to answer.",
            title="Proof of life required",
            priority="high",
            tags="warning",
        )
        LOG.info(
            "Prompted for password, attempt %d of %d",
            challenge.attempt,
            self.settings.attempts,
        )

        challenge.prompt_at = sent_at
        challenge.interrupted = False
        if challenge.cursor is None:
            challenge.cursor = str(int(sent_at.timestamp()))

    def _await_reply(
        self, challenge: Challenge, save: Callable[[], None]
    ) -> Message | None:
        deadline = challenge.prompt_at + self.settings.reply_window
        while True:
            try:
                messages = self.ntfy.poll(self.settings.reply_topic, challenge.cursor)
            except NtfyError:
                challenge.interrupted = True
                save()
                raise

            if messages:
                challenge.cursor = messages[0].id
                save()
                return messages[0]

            remaining = (deadline - self.clock.now()).total_seconds()
            if remaining <= 0:
                return None
            self.clock.sleep(min(POLL_SECONDS, remaining))


def first_password(
    challenger: Challenger, since: str | None, now: datetime
) -> tuple[bool, str]:
    """Read every reply after `since`; True if any is the password. Returns the new cursor."""

    cursor = since or str(int(now.timestamp()))
    found = False
    for message in challenger.ntfy.poll(challenger.settings.reply_topic, cursor):
        cursor = message.id
        if challenger.is_password(message.text):
            found = True
            break
        LOG.warning("Wrong password received on the reply topic")
    return found, cursor
