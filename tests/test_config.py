"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for loading config.toml
"""

from datetime import timedelta

import pytest

from datakrash import config
from datakrash.config import ConfigError, format_duration, parse_duration

ENV = {"NTFY": "ntfy-token", "GH": "gh-token"}


def _data(**overrides):
    data = {
        "system": {"trigger": "12h"},
        "challenge": {
            "topic": "prompt",
            "reply_topic": "reply",
            "token_env": "NTFY",
            "password_file": "/tmp/password.hash",
            "reply_window": "1h",
        },
        "contact": {
            "name": "Test Contact",
            "email": "contact@example.com",
            "message": "/tmp/message.txt",
        },
        "service": {
            "github": {"enabled": True, "username": "someone", "duration": "3d"}
        },
    }
    for section, table in overrides.items():
        data[section] = table
    return data


@pytest.mark.parametrize(
    "text, expected",
    [
        ("12h", timedelta(hours=12)),
        ("3d", timedelta(days=3)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("0h", timedelta(0)),
    ],
)
def test_parses_durations(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["3d", "12h", "1h30m", "1d1h30m", "0m"])
def test_formats_durations_back(text):
    assert format_duration(parse_duration(text)) == text


@pytest.mark.parametrize("text", ["3", "-1d", "3w", "", "h", "1.5h", 3])
def test_rejects_bad_durations(text):
    with pytest.raises(ConfigError):
        parse_duration(text)


def test_loads_a_valid_config():
    loaded = config.parse(_data(), ENV)

    assert loaded.system.trigger == timedelta(hours=12)
    assert loaded.challenge.token == "ntfy-token"
    assert loaded.challenge.attempts == 3
    assert loaded.contact.schedule[0] == timedelta(0)
    assert loaded.contact.schedule[-1] == timedelta(days=6)
    assert list(loaded.services) == ["github"]
    assert loaded.services["github"]["duration"] == timedelta(days=3)


def test_contact_needs_a_channel():
    contact = {"name": "Test Contact", "message": "/tmp/message.txt"}
    with pytest.raises(ConfigError, match="email, a phone"):
        config.parse(_data(contact=contact), ENV)


def test_secret_from_environment():
    service = {
        "github": {
            "enabled": True,
            "username": "someone",
            "token_env": "GH",
            "duration": "1d",
        }
    }
    loaded = config.parse(_data(service=service), ENV)

    assert loaded.services["github"]["token"] == "gh-token"
    assert "token_env" not in loaded.services["github"]


def test_missing_secret_fails_loudly():
    with pytest.raises(ConfigError, match="NTFY"):
        config.parse(_data(), {})


def test_disabled_services_are_left_out():
    service = {
        "github": {"enabled": True, "username": "someone", "duration": "1d"},
        "garmin": {"enabled": False},
    }
    assert list(config.parse(_data(service=service), ENV).services) == ["github"]


def test_needs_at_least_one_enabled_service():
    with pytest.raises(ConfigError, match="nothing to watch"):
        config.parse(_data(service={"github": {"enabled": False}}), ENV)


def test_services_keep_file_order():
    service = {
        "zeta": {"enabled": True, "duration": "1d"},
        "alpha": {"enabled": True, "duration": "1d"},
    }
    assert list(config.parse(_data(service=service), ENV).services) == ["zeta", "alpha"]


def test_example_config_is_valid():
    example = config.load(
        config.Path(__file__).parent.parent / "config.example.toml",
        {
            "DATAKRASH_NTFY_TOKEN": "x",
            "DATAKRASH_SMTP_PASSWORD": "x",
            "DATAKRASH_TWILIO_TOKEN": "x",
            "DATAKRASH_GITHUB_TOKEN": "x",
        },
    )
    assert "github" in example.services


def test_system_section_needs_no_secrets(monkeypatch):
    monkeypatch.delenv("DATAKRASH_NTFY_TOKEN", raising=False)
    system = config.system_section(
        config.Path(__file__).parent.parent / "config.example.toml"
    )
    assert system.trigger == timedelta(hours=12)
