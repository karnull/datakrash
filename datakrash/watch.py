"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  One run of the switch: check services, challenge the owner, message the contact
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from datakrash.challenge import Challenger, first_password
from datakrash.clock import Clock
from datakrash.config import ContactConfig, format_duration
from datakrash.notifier import Notifier, NotifyFailed
from datakrash.ntfy import NtfyError
from datakrash.service import CheckFailed, Service
from datakrash.state import (
    ARMED,
    CHALLENGE,
    FIRED,
    SPENT,
    Challenge,
    Send,
    State,
    StateCorrupt,
    StateStore,
)

LOG = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TEMPFAIL = 75

FIRED_POLL_SECONDS = 60


@dataclass
class Watch:
    services: list[Service]
    routes: list[tuple[Notifier, str]]
    contact: ContactConfig
    challenger: Challenger
    store: StateStore
    clock: Clock

    def run(self) -> int:
        state = self._load()
        try:
            code, outcome = self._step(state)
        except NtfyError as exc:
            LOG.error("%s; systemd will retry", exc)
            code, outcome = EXIT_TEMPFAIL, "ntfy unreachable"
        except NotifyFailed as exc:
            LOG.error("Could not message the contact: %s; systemd will retry", exc)
            code, outcome = EXIT_FAILED, "contact delivery failed"

        state.last_run = self.clock.now()
        state.last_outcome = outcome
        self.store.save(state)
        LOG.info("Run finished: %s", outcome)
        return code

    # ==========================================================================
    # Phases

    def _step(self, state: State) -> tuple[int, str]:
        if state.phase == FIRED:
            return self._work_schedule(state)

        if self._any_activity(state):
            if state.phase != ARMED:
                self.challenger.notice("Activity seen. The switch is armed again.")
            state.rearm()
            return EXIT_OK, "activity"

        if state.phase == SPENT:
            LOG.info(
                "Every message to the contact has been sent; waiting for activity to re-arm"
            )
            return EXIT_OK, "spent"

        state.phase = CHALLENGE
        state.challenge = state.challenge or Challenge()
        self.store.save(state)

        if self.challenger.run(state.challenge, lambda: self.store.save(state)):
            state.rearm()
            state.last_activity = self.clock.now()
            return EXIT_OK, "password confirmed"

        self._fire(state)
        return self._work_schedule(state)

    def _fire(self, state: State) -> None:
        now = self.clock.now()
        LOG.critical(
            "No proof of life after %d attempts; messaging the contact",
            self.challenger.settings.attempts,
        )

        state.phase = FIRED
        state.challenge = None
        state.fired_at = now
        state.sends = [Send(due=now + offset) for offset in self.contact.schedule]
        state.reply_cursor = str(int(now.timestamp()))
        self.store.save(state)

        self.challenger.notice(
            f"No proof of life. Your contact is being messaged {len(state.sends)} times over the coming days. "
            f"Reply with your password on {self.challenger.settings.reply_topic} to stop further messages.",
            title="Datakrash fired",
        )

    def _work_schedule(self, state: State) -> tuple[int, str]:
        while send := self._next_send(state):
            if self._wait_for(send.due, state):
                return self._stand_down(state, "password confirmed")
            if self._any_activity(state):
                return self._stand_down(state, "activity")
            self._deliver(send, state)

        state.phase = SPENT
        self.challenger.notice("Every scheduled message has been sent to your contact.")
        return EXIT_OK, "schedule complete"

    def _stand_down(self, state: State, reason: str) -> tuple[int, str]:
        sent = sum(1 for send in state.sends if send.delivered)
        LOG.warning(
            "Standing down after %d message(s) to the contact: %s", sent, reason
        )
        self.challenger.notice(
            f"Stood down ({reason}). No further messages will be sent to your contact."
        )
        state.rearm()
        state.last_activity = self.clock.now()
        return EXIT_OK, f"stood down: {reason}"

    # ==========================================================================
    # Helpers

    def _load(self) -> State:
        try:
            return self.store.load()
        except StateCorrupt as exc:
            moved = self.store.quarantine(self.clock.now())
            LOG.error("%s; moved to %s and starting armed", exc, moved)
            self.challenger.notice(
                f"The state file was unreadable and was moved to {moved}. Starting armed."
            )
            return State()

    def _any_activity(self, state: State) -> bool:
        now = self.clock.now()
        for service in self.services:
            try:
                active = service.check_activity(now - service.duration)
            except CheckFailed as exc:
                LOG.warning("%s: failed to connect: %s", service.name, exc)
                self.challenger.notice(f"The {service.name} check failed to connect.")
                continue

            if active:
                LOG.info(
                    "%s: activity in the last %s",
                    service.name,
                    format_duration(service.duration),
                )
                state.last_activity = now
                return True
            LOG.info(
                "%s: no activity in the last %s",
                service.name,
                format_duration(service.duration),
            )
        return False

    def _channels(self) -> set[str]:
        return {notifier.channel for notifier, _ in self.routes}

    def _next_send(self, state: State) -> Send | None:
        pending = [
            send
            for send in state.sends
            if not send.skipped and not self._channels() <= set(send.delivered)
        ]
        overdue = [send for send in pending if send.due <= self.clock.now()]

        # after a long outage, several sends are due at once; the contact gets one, not a burst
        for send in overdue[:-1]:
            LOG.warning(
                "Skipping the message due at %s, as a later one is also due",
                send.due.isoformat(),
            )
            send.skipped = True
        if overdue[:-1]:
            self.store.save(state)

        remaining = [send for send in pending if not send.skipped]
        return remaining[0] if remaining else None

    def _wait_for(self, due: datetime, state: State) -> bool:
        """Sleep until `due`, reading the reply topic on the way. True if the password arrives."""

        while True:
            try:
                found, cursor = first_password(
                    self.challenger, state.reply_cursor, self.clock.now()
                )
                if cursor != state.reply_cursor:
                    state.reply_cursor = cursor
                    self.store.save(state)
                if found:
                    return True
            except NtfyError as exc:
                LOG.warning("Cannot read replies while waiting: %s", exc)

            remaining = (due - self.clock.now()).total_seconds()
            if remaining <= 0:
                return False
            self.clock.sleep(min(FIRED_POLL_SECONDS, remaining))

    def _deliver(self, send: Send, state: State) -> None:
        try:
            body = self.contact.message.read_text()
        except OSError as exc:
            raise NotifyFailed(
                f"cannot read the message file {self.contact.message}: {exc.strerror}"
            ) from exc

        number = state.sends.index(send) + 1
        failures = []
        for notifier, address in self.routes:
            if notifier.channel in send.delivered:
                continue
            try:
                notifier.send(address, self.contact.subject, body)
            except NotifyFailed as exc:
                LOG.error(
                    "Message %d of %d via %s failed: %s",
                    number,
                    len(state.sends),
                    notifier.channel,
                    exc,
                )
                failures.append(notifier.channel)
                continue
            send.delivered.append(notifier.channel)
            self.store.save(state)
            LOG.warning(
                "Message %d of %d sent to the contact via %s",
                number,
                len(state.sends),
                notifier.channel,
            )

        if failures:
            raise NotifyFailed(f"undelivered via {', '.join(failures)}")
