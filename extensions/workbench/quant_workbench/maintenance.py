"""Operator-only maintenance composition root (PHYSICAL_CONTRACT §6.1).

This is not a service port and is never constructed by ``bootstrap``/``api``.
It exists so CLI parsing stays free of storage imports and so operator commands
(migration, verification, future backup/GC audit) have one owner. It performs
no engine, network or research work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .adapters.storage.migrations import (MigrationError, SUPPORTED_SCHEMA,   # noqa: F401
                                          database_path, migrate, status, verify)


def storage_status(root: str | Path) -> dict[str, Any]:
    return status(root)


def storage_migrate(root: str | Path, backup: str | Path,
                    confirmed_attempts: Iterable[str] = ()) -> dict[str, Any]:
    return migrate(root, backup, confirmed_attempts)


def storage_verify(root: str | Path) -> dict[str, Any]:
    return verify(database_path(root))
