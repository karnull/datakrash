"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for the service registry and the GitHub service
"""

import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from deadman_switch import service
from deadman_switch.config import ConfigError
from deadman_switch.service import CheckFailed
from deadman_switch.service.github import GitHub

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=3)


def _github(handler, **settings):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHub(
        "github",
        {"username": "someone", "duration": timedelta(days=3), **settings},
        http=http,
    )


def _events(*created):
    return lambda request: httpx.Response(
        200, json=[{"created_at": stamp} for stamp in created]
    )


def test_lists_shipped_services():
    assert "github" in service.available()


def test_discovers_a_new_service_module(tmp_path, monkeypatch):
    (tmp_path / "carrier_pigeon.py").write_text(
        "from deadman_switch.service.base import Service\n"
        "class CarrierPigeon(Service):\n"
        "    def check_activity(self, since):\n"
        "        return True\n"
    )
    monkeypatch.setattr(service, "__path__", [*service.__path__, str(tmp_path)])
    monkeypatch.delitem(
        sys.modules, "deadman_switch.service.carrier_pigeon", raising=False
    )

    [built] = service.build({"carrier_pigeon": {"duration": timedelta(days=1)}})
    assert built.check_activity(SINCE) is True


def test_unknown_service_is_a_config_error():
    with pytest.raises(ConfigError, match="no module"):
        service.build({"telepathy": {"duration": timedelta(days=1)}})


def test_github_event_inside_window_is_activity():
    assert _github(_events("2026-10-24T12:00:00Z")).check_activity(SINCE) is True


def test_github_event_on_the_boundary_is_activity():
    assert _github(_events("2026-10-23T12:00:00Z")).check_activity(SINCE) is True


def test_github_event_outside_window_is_silence():
    assert _github(_events("2026-10-23T11:59:59Z")).check_activity(SINCE) is False


def test_github_compares_offsets_in_utc():
    # 21:30 at +10:00 is 11:30 UTC, half an hour before the window opens
    assert _github(_events("2026-10-23T21:30:00+10:00")).check_activity(SINCE) is False


def test_github_no_events_is_silence():
    assert _github(_events()).check_activity(SINCE) is False


def test_github_server_error_is_a_failed_check():
    with pytest.raises(CheckFailed):
        _github(lambda request: httpx.Response(500)).check_activity(SINCE)


def test_github_network_error_is_a_failed_check():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(CheckFailed):
        _github(refuse).check_activity(SINCE)


def test_github_sends_the_token():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[])

    _github(handler, token="gh-token").check_activity(SINCE)
    assert seen["auth"] == "Bearer gh-token"
