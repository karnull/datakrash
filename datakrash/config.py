"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Loads and validates config.toml
"""

# ==============================================================================
# Imports

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

DEFAULT_PATH = Path("/etc/datakrash/config.toml")
DEFAULT_STATE = Path("/var/lib/datakrash/state.json")
DEFAULT_SCHEDULE = ("0h", "1h30m", "3h", "1d", "2d", "3d", "4d", "5d", "6d")

_DURATION = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?")


class ConfigError(Exception):
    pass


# ==============================================================================
# Data


@dataclass(frozen=True)
class SystemConfig:
    trigger: timedelta
    state: Path


@dataclass(frozen=True)
class ChallengeConfig:
    server: str
    topic: str
    reply_topic: str
    token: str
    password_file: Path
    reply_window: timedelta
    attempts: int


@dataclass(frozen=True)
class ContactConfig:
    name: str
    email: str
    phone: str
    message: Path
    subject: str
    schedule: tuple[timedelta, ...]


@dataclass(frozen=True)
class Config:
    system: SystemConfig
    challenge: ChallengeConfig
    contact: ContactConfig
    notifiers: dict[str, dict[str, Any]] = field(default_factory=dict)
    services: dict[str, dict[str, Any]] = field(default_factory=dict)


# ==============================================================================
# Parsing Helpers


def parse_duration(text: str) -> timedelta:
    """Parse durations such as "3d", "12h", "1h30m" or "0h"."""

    match = _DURATION.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match or not any(match.groups()):
        raise ConfigError(
            f"{text!r} is not a duration; use forms like 3d, 12h or 1h30m"
        )

    days, hours, minutes = (int(group or 0) for group in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)


def format_duration(duration: timedelta) -> str:
    """The inverse of parse_duration: 1 day 1 hour 30 minutes becomes "1d1h30m"."""

    minutes = int(duration.total_seconds() // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = [
        f"{value}{unit}"
        for value, unit in ((days, "d"), (hours, "h"), (minutes, "m"))
        if value
    ]
    return "".join(parts) or "0m"


def _positive_duration(table: Mapping[str, Any], key: str, where: str) -> timedelta:
    duration = parse_duration(_require(table, key, where))
    if duration <= timedelta(0):
        raise ConfigError(f"{where}.{key} must be longer than zero")
    return duration


def _require(table: Mapping[str, Any], key: str, where: str) -> Any:
    value = table.get(key)
    if value is None or value == "":
        raise ConfigError(f"{where}.{key} is required")
    return value


def _table(data: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a table")
    return value


def resolve_secrets(
    table: Mapping[str, Any], where: str, env: Mapping[str, str]
) -> dict[str, Any]:
    """Replace every `<name>_env = "VAR"` key with `<name>` read from the environment."""

    resolved = {}
    for key, value in table.items():
        if not key.endswith("_env"):
            resolved[key] = value
            continue

        name = key.removesuffix("_env")
        if name in table:
            raise ConfigError(f"{where} sets both {name} and {key}; use one")
        if value not in env or env[value] == "":
            raise ConfigError(
                f"{where}.{key} names {value}, which is not set in the environment"
            )
        resolved[name] = env[value]
    return resolved


# ==============================================================================
# Sections


def _system(data: Mapping[str, Any]) -> SystemConfig:
    table = _table(data, "system")
    return SystemConfig(
        trigger=_positive_duration(table, "trigger", "system"),
        state=Path(table.get("state") or DEFAULT_STATE),
    )


def _challenge(data: Mapping[str, Any], env: Mapping[str, str]) -> ChallengeConfig:
    table = resolve_secrets(_table(data, "challenge"), "challenge", env)

    attempts = table.get("attempts", 3)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ConfigError("challenge.attempts must be a whole number of at least 1")

    topic = _require(table, "topic", "challenge")
    reply_topic = _require(table, "reply_topic", "challenge")
    if topic == reply_topic:
        raise ConfigError("challenge.topic and challenge.reply_topic must differ")

    return ChallengeConfig(
        server=str(table.get("server") or "https://ntfy.sh").rstrip("/"),
        topic=topic,
        reply_topic=reply_topic,
        token=_require(table, "token", "challenge"),
        password_file=Path(_require(table, "password_file", "challenge")),
        reply_window=_positive_duration(table, "reply_window", "challenge"),
        attempts=attempts,
    )


def _contact(data: Mapping[str, Any]) -> ContactConfig:
    table = _table(data, "contact")

    email = table.get("email", "") or ""
    phone = table.get("phone", "") or ""
    if not email and not phone:
        raise ConfigError("contact needs an email, a phone, or both")

    schedule = table.get("schedule", list(DEFAULT_SCHEDULE))
    if not isinstance(schedule, list) or not schedule:
        raise ConfigError("contact.schedule must be a non-empty list of durations")
    offsets = tuple(sorted(parse_duration(offset) for offset in schedule))

    return ContactConfig(
        name=_require(table, "name", "contact"),
        email=email,
        phone=phone,
        message=Path(_require(table, "message", "contact")),
        subject=table.get("subject") or "A message left for you",
        schedule=offsets,
    )


def _notifiers(
    data: Mapping[str, Any], env: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    notifiers = {}
    for channel, table in _table(data, "notifier").items():
        where = f"notifier.{channel}"
        if not isinstance(table, dict):
            raise ConfigError(f"[{where}] must be a table")
        resolved = resolve_secrets(table, where, env)
        _require(resolved, "provider", where)
        notifiers[channel] = resolved
    return notifiers


def _services(
    data: Mapping[str, Any], env: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    services = {}
    for name, table in _table(data, "service").items():
        where = f"service.{name}"
        if not isinstance(table, dict):
            raise ConfigError(f"[{where}] must be a table")

        enabled = table.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{where}.enabled must be true or false")
        if not enabled:
            continue

        resolved = resolve_secrets(table, where, env)
        resolved["duration"] = _positive_duration(table, "duration", where)
        services[name] = resolved

    if not services:
        raise ConfigError("no service is enabled, so there is nothing to watch")
    return services


# ==============================================================================
# Public API


def parse(data: Mapping[str, Any], env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    return Config(
        system=_system(data),
        challenge=_challenge(data, env),
        contact=_contact(data),
        notifiers=_notifiers(data, env),
        services=_services(data, env),
    )


def load(path: Path, env: Mapping[str, str] | None = None) -> Config:
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    return parse(data, env)


def password_path(path: Path) -> Path:
    """Read only challenge.password_file, so the password can be set before secrets exist."""

    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    return Path(_require(_table(data, "challenge"), "password_file", "challenge"))
