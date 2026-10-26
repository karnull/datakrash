"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Finds activity services by module name, so new ones need no registration
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from deadman_switch.config import ConfigError
from deadman_switch.service.base import CheckFailed, Service

__all__ = ["CheckFailed", "Service", "available", "build"]

_INTERNAL = {"base"}


def available() -> list[str]:
    return sorted(
        module.name
        for module in pkgutil.iter_modules(__path__)
        if module.name not in _INTERNAL
    )


def load(name: str) -> type[Service]:
    if name not in available():
        raise ConfigError(
            f"[service.{name}] has no module; available: {', '.join(available())}"
        )

    module = importlib.import_module(f"{__name__}.{name}")
    classes = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, Service)
        and cls is not Service
        and cls.__module__ == module.__name__
    ]
    if len(classes) != 1:
        raise ConfigError(
            f"service module {name} must define exactly one Service subclass"
        )
    return classes[0]


def build(services: dict[str, dict[str, Any]]) -> list[Service]:
    return [load(name)(name, settings) for name, settings in services.items()]
