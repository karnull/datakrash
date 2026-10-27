"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Tests for the rendered systemd units
"""

from datetime import timedelta
from pathlib import Path

from datakrash import units


def _render():
    return units.render(
        executable=Path("/usr/local/bin/datakrash"),
        config=Path("/etc/datakrash/config.toml"),
        user="watcher",
        trigger=timedelta(hours=12),
    )


def test_timer_interval_follows_the_trigger():
    assert "OnUnitActiveSec=43200s" in _render()["datakrash.timer"]


def test_service_runs_the_switch_with_retries():
    service = _render()["datakrash.service"]

    assert (
        "ExecStart=/usr/local/bin/datakrash --config /etc/datakrash/config.toml run"
        in service
    )
    assert "User=watcher" in service
    assert "RestartSec=5min" in service
    assert "TimeoutStartSec=infinity" in service


def test_writes_both_units(tmp_path):
    written = units.write(tmp_path, _render())
    assert sorted(path.name for path in written) == [
        "datakrash.service",
        "datakrash.timer",
    ]
