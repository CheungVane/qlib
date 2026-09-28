"""Single-machine storage facade: SQLite metadata + content-addressed objects.

Composition of the split modules (third-review C4): schema/connection/object store and shared
helpers live in `storage_base`, then one mixin per domain. `LocalResultRepository` keeps the
public surface the rest of the code and the tests rely on, including `_connect`, `objects` and
the re-exported schema constants.
"""

from __future__ import annotations

from .storage_base import *  # noqa: F401,F403 - re-export constants, errors and helpers
from .storage_attempts import AttemptsMixin
from .storage_factors import FactorsMixin
from .storage_results import ResultsMixin


class LocalResultRepository(SqliteStore, ResultsMixin, AttemptsMixin, FactorsMixin):
    """Metadata repository over SQLite plus immutable content-addressed objects."""
