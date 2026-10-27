"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  The switch's memory between runs, written atomically
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ARMED = "armed"
CHALLENGE = "challenge"
FIRED = "fired"
SPENT = "spent"


class StateCorrupt(Exception):
    pass


@dataclass
class Challenge:
    attempt: int = 1
    prompt_at: datetime | None = None
    # ntfy `since` value: where reading the reply topic resumes
    cursor: str | None = None
    # ntfy dropped out while waiting, so this attempt gets a fresh prompt
    interrupted: bool = False


@dataclass
class Send:
    due: datetime
    delivered: list[str] = field(default_factory=list)
    skipped: bool = False


@dataclass
class State:
    phase: str = ARMED
    challenge: Challenge | None = None
    fired_at: datetime | None = None
    sends: list[Send] = field(default_factory=list)
    reply_cursor: str | None = None
    last_run: datetime | None = None
    last_outcome: str = ""
    last_activity: datetime | None = None

    def rearm(self) -> None:
        self.phase = ARMED
        self.challenge = None
        self.fired_at = None
        self.sends = []
        self.reply_cursor = None


# ==============================================================================
# Serialisation


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    return value


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _decode(data: dict[str, Any]) -> State:
    challenge = data.get("challenge")
    return State(
        phase=data.get("phase", ARMED),
        challenge=Challenge(
            attempt=challenge["attempt"],
            prompt_at=_time(challenge.get("prompt_at")),
            cursor=challenge.get("cursor"),
            interrupted=challenge.get("interrupted", False),
        )
        if challenge
        else None,
        fired_at=_time(data.get("fired_at")),
        sends=[
            Send(
                due=_time(send["due"]),
                delivered=list(send.get("delivered", [])),
                skipped=send.get("skipped", False),
            )
            for send in data.get("sends", [])
        ],
        reply_cursor=data.get("reply_cursor"),
        last_run=_time(data.get("last_run")),
        last_outcome=data.get("last_outcome", ""),
        last_activity=_time(data.get("last_activity")),
    )


# ==============================================================================
# Store


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> State:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return State()

        try:
            state = _decode(json.loads(text))
        except (ValueError, KeyError, TypeError) as exc:
            raise StateCorrupt(
                f"{self.path} cannot be read: {type(exc).__name__}: {exc}"
            ) from exc
        if state.phase not in (ARMED, CHALLENGE, FIRED, SPENT):
            raise StateCorrupt(f"{self.path} has an unknown phase {state.phase!r}")
        return state

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=".state-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(_encode(asdict(state)), handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def quarantine(self, now: datetime) -> Path:
        """Move an unreadable state file aside so it can be inspected later."""

        target = self.path.with_name(f"{self.path.name}.corrupt-{now:%Y%m%dT%H%M%SZ}")
        os.replace(self.path, target)
        return target
