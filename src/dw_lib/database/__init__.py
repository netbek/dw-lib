from .adapters.types import (
    ClickHouseRelation,
    ClickHouseSettings,
    DuckDBRelation,
    DuckDBSettings,
    PostgresRelation,
    PostgresSettings,
)
from .utils import render_statement
from typing import TYPE_CHECKING

import lazy_loader as lazy

if TYPE_CHECKING:
    from .adapters.clickhouse import ClickHouseAdapter
    from .adapters.duckdb import DuckDBAdapter
    from .adapters.postgres import PostgresAdapter

__all__ = [
    "ClickHouseAdapter",
    "ClickHouseRelation",
    "ClickHouseSettings",
    "DuckDBAdapter",
    "DuckDBRelation",
    "DuckDBSettings",
    "PostgresAdapter",
    "PostgresRelation",
    "PostgresSettings",
    "render_statement",
]


__getattr__, __dir__, _ = lazy.attach(
    __name__,
    submod_attrs={
        "adapters.clickhouse": ["ClickHouseAdapter"],
        "adapters.duckdb": ["DuckDBAdapter"],
        "adapters.postgres": ["PostgresAdapter"],
    },
)
