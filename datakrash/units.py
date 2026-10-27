"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Renders the systemd service and timer for the switch
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from datakrash.config import format_duration

SERVICE = """\
[Unit]
Description=Datakrash: check for proof of life
Wants=network-online.target
After=network-online.target
# retry every 5 minutes for as long as it takes
StartLimitIntervalSec=0

[Service]
Type=oneshot
User={user}
ExecStart={executable} --config {config} run
# a challenge waits through every reply window, and a fired switch works through a week of messages
TimeoutStartSec=infinity
StateDirectory=datakrash
StateDirectoryMode=0700
EnvironmentFile=-/etc/datakrash/env
Restart=on-failure
RestartSec=5min
"""

TIMER = """\
[Unit]
Description=Run datakrash every {trigger}

[Timer]
OnBootSec=5min
OnUnitActiveSec={seconds}s
Unit=datakrash.service

[Install]
WantedBy=timers.target
"""


def render(
    *, executable: Path, config: Path, user: str, trigger: timedelta
) -> dict[str, str]:
    return {
        "datakrash.service": SERVICE.format(
            executable=executable, config=config.resolve(), user=user
        ),
        "datakrash.timer": TIMER.format(
            trigger=format_duration(trigger), seconds=int(trigger.total_seconds())
        ),
    }


def write(out: Path, units: dict[str, str]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in units.items():
        path = out / name
        path.write_text(text)
        written.append(path)
    return written
