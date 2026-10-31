"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Main file
"""


# ==============================================================================
# Imports

from __future__ import annotations

import argparse
import getpass
import logging
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Sequence

import colorlog

from datakrash import config, notifier, password, service, units
from datakrash.challenge import Challenger
from datakrash.clock import Clock
from datakrash.notifier.printer import Printer
from datakrash.ntfy import Ntfy
from datakrash.service import CheckFailed
from datakrash.service.base import Service
from datakrash.state import StateStore
from datakrash.watch import EXIT_FAILED, EXIT_OK, Watch

LOG = logging.getLogger(__name__)

DRILL_REPLY_WINDOW = timedelta(seconds=60)
DRILL_SPEED = 3600
DRILL_PREFIX = "[DRILL] "


class Quiet(Service):
    """Stands in for a real service in `drill --silent`."""

    def check_activity(self, since) -> bool:
        return False


class _DrillFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith(DRILL_PREFIX):
            record.msg = f"{DRILL_PREFIX}{record.msg}"
        return True


def _mark_drill() -> None:
    for handler in logging.getLogger().handlers:
        handler.addFilter(_DrillFilter())


# ==============================================================================
# Helper Functions


def _build_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Track yourself. Trigger actions when unreachable.",
    )

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (repeat: -v, -vv).",
    )
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output (warnings/errors only).",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"],
        default=None,
        help="Explicit log level (overrides -v/-q).",
    )

    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional path to a log file.",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=config.DEFAULT_PATH,
        help=f"Path to config.toml (default: {config.DEFAULT_PATH}).",
    )

    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser(
        "run", help="Check services and act on the result; what the timer runs."
    )
    commands.add_parser(
        "check", help="Show each service's result without challenging or notifying."
    )

    drill = commands.add_parser(
        "drill", help="Rehearse a full run with nothing sent to the contact."
    )
    drill.add_argument(
        "--silent",
        action="store_true",
        help="Treat every service as quiet, so the challenge always starts.",
    )

    commands.add_parser("set-password", help="Set the password the challenge asks for.")

    units_parser = commands.add_parser(
        "systemd-units", help="Write the systemd service and timer."
    )
    units_parser.add_argument(
        "--out", type=Path, required=True, help="Directory to write the units to."
    )
    units_parser.add_argument(
        "--user",
        default=getpass.getuser(),
        help="User the service runs as (default: the current user).",
    )

    return parser


def _resolve_log_level(args: argparse.Namespace) -> int:
    """Derive log level from args with sane precedence."""

    if args.log_level:
        return getattr(logging, args.log_level)

    if args.quiet:
        return logging.WARN

    # default INFO, -vv => DEBUG
    if args.verbose >= 2:
        return logging.DEBUG
    return logging.INFO


def _configure_logging(level: int, log_file: str | None) -> None:
    """
    Configure root logging.

    Uses colorlog when stderr is a TTY; otherwise uses plain formatter
    to avoid ANSI escape codes in redirected output.
    """

    root = logging.getLogger()
    root.setLevel(level)
    # request URLs carry ntfy topic names and account ids, which stay out of the journal
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root.handlers.clear()

    is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    stream_handler = logging.StreamHandler(sys.stderr)

    if is_tty:
        formatter = colorlog.ColoredFormatter(
            fmt="%(log_color)s%(levelname)s%(reset)s\t%(asctime)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARN": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    else:
        formatter = logging.Formatter(
            fmt="%(levelname)s\t%(asctime)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(levelname)s\t%(asctime)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S %z",
            )
        )
        root.addHandler(file_handler)


# ==============================================================================
# Program Start Point


def _build_watch(
    cfg: config.Config, *, drill: bool = False, silent: bool = False
) -> Watch:
    stored_hash = password.read(cfg.challenge.password_file)
    if not cfg.contact.message.is_file():
        raise config.ConfigError(
            f"contact.message {cfg.contact.message} does not exist"
        )

    settings = cfg.challenge
    contact = cfg.contact
    services = service.build(cfg.services)
    routes = notifier.routes(contact, notifier.build(cfg.notifiers))
    store = StateStore(cfg.system.state)

    if drill:
        settings = replace(settings, reply_window=DRILL_REPLY_WINDOW)
        contact = replace(
            contact, schedule=tuple(offset / DRILL_SPEED for offset in contact.schedule)
        )
        routes = [
            (Printer(n.channel, n.address_field), address) for n, address in routes
        ]
        store = StateStore(
            Path(tempfile.mkdtemp(prefix="datakrash-drill-")) / "state.json"
        )
        if silent:
            services = [Quiet(s.name, s.settings) for s in services]

    clock = Clock()
    ntfy = Ntfy(settings.server, settings.token)
    challenger = Challenger(
        settings, ntfy, stored_hash, clock, label=DRILL_PREFIX if drill else ""
    )
    return Watch(services, routes, contact, challenger, store, clock)


def _check(cfg: config.Config) -> int:
    now = Clock().now()
    for svc in service.build(cfg.services):
        try:
            result = (
                "activity" if svc.check_activity(now - svc.duration) else "no activity"
            )
        except CheckFailed as exc:
            result = f"failed to connect ({exc})"
        print(
            f"{svc.name}: {result} in the last {config.format_duration(svc.duration)}"
        )
    return EXIT_OK


def _set_password(path: Path) -> int:
    target = config.password_path(path)
    first = getpass.getpass("New password: ")
    if not first.strip():
        LOG.error("The password cannot be empty")
        return EXIT_FAILED
    if getpass.getpass("Again: ") != first:
        LOG.error("The passwords do not match; nothing was changed")
        return EXIT_FAILED

    password.write(target, first.strip())
    LOG.info("Password hash written to %s", target)
    return EXIT_OK


def _systemd_units(system: config.SystemConfig, args: argparse.Namespace) -> int:
    executable = shutil.which("datakrash") or Path(sys.argv[0]).resolve()
    rendered = units.render(
        executable=Path(executable),
        config=args.config,
        user=args.user,
        trigger=system.trigger,
    )
    for path in units.write(args.out, rendered):
        LOG.info("Wrote %s", path)
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    LOG.debug("Arguments: %s", args)

    if args.command == "set-password":
        return _set_password(args.config)

    if args.command == "systemd-units":
        return _systemd_units(config.system_section(args.config), args)

    cfg = config.load(args.config)

    if args.command == "check":
        return _check(cfg)

    if args.command == "drill":
        _mark_drill()
        LOG.info(
            "Drill: the contact schedule runs %d times faster than real time",
            DRILL_SPEED,
        )
        return _build_watch(cfg, drill=True, silent=args.silent).run()

    return _build_watch(cfg).run()


def main(argv: Sequence[str] | None = None) -> int:
    start = time.perf_counter()

    # Use module name as a sensible default program name.
    prog = (sys.argv[0].rsplit("/", 1)[-1] or "app") if argv is None else "app"

    parser = _build_parser(prog=prog)

    args = parser.parse_args(argv)

    level = _resolve_log_level(args)
    _configure_logging(level=level, log_file=args.log_file)

    try:
        code = run(args)
        return int(code) if code is not None else 0

    except (config.ConfigError, password.PasswordError) as exc:
        LOG.error("%s", exc)
        return EXIT_FAILED

    except KeyboardInterrupt:
        LOG.warning("Interrupted by user (Ctrl+C).")
        return 130  # conventional SIGINT exit code

    except Exception:
        LOG.exception("Unhandled exception")
        return 1

    finally:
        elapsed = time.perf_counter() - start
        LOG.debug("Elapsed: %.3fs", elapsed)


if __name__ == "__main__":
    raise SystemExit(main())
