"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Finds notifiers by provider name, so new ones need no registration
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from deadman_switch.config import ConfigError, ContactConfig
from deadman_switch.notifier.base import Notifier, NotifyFailed

__all__ = ["Notifier", "NotifyFailed", "available", "build", "routes"]

_INTERNAL = {"base", "printer"}


def available() -> list[str]:
    return sorted(
        module.name
        for module in pkgutil.iter_modules(__path__)
        if module.name not in _INTERNAL
    )


def load(provider: str) -> type[Notifier]:
    if provider not in available():
        raise ConfigError(
            f"no notifier provider called {provider}; available: {', '.join(available())}"
        )

    module = importlib.import_module(f"{__name__}.{provider}")
    classes = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, Notifier)
        and cls is not Notifier
        and cls.__module__ == module.__name__
    ]
    if len(classes) != 1:
        raise ConfigError(
            f"notifier module {provider} must define exactly one Notifier subclass"
        )
    return classes[0]


def build(notifiers: dict[str, dict[str, Any]]) -> dict[str, Notifier]:
    return {
        channel: load(settings["provider"])(channel, settings)
        for channel, settings in notifiers.items()
    }


def routes(
    contact: ContactConfig, notifiers: dict[str, Notifier]
) -> list[tuple[Notifier, str]]:
    """Pair each notifier with the contact address it delivers to; every address set needs one."""

    pairs = []
    for field in ("email", "phone"):
        address = getattr(contact, field)
        if not address:
            continue
        matching = [
            notifier
            for notifier in notifiers.values()
            if notifier.address_field == field
        ]
        if not matching:
            raise ConfigError(
                f"contact.{field} is set but no [notifier.*] delivers to a {field}"
            )
        pairs.extend((notifier, address) for notifier in matching)
    return pairs
