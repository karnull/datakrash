"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  scrypt password hashing for the proof-of-life challenge
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

N, R, P, LENGTH = 2**14, 8, 1, 32


class PasswordError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=LENGTH)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def verify(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.strip().split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest)),
        )
    except ValueError:
        return False
    return hmac.compare_digest(candidate, bytes.fromhex(digest))


def read(path: Path) -> str:
    try:
        stored = path.read_text().strip()
    except OSError as exc:
        raise PasswordError(
            f"cannot read the password hash at {path}; run set-password first"
        ) from exc
    if not stored.startswith("scrypt$"):
        raise PasswordError(
            f"{path} does not hold a password hash; run set-password again"
        )
    return stored


def write(path: Path, password: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(hash_password(password) + "\n")
    os.chmod(path, 0o600)
