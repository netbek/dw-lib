from .types import (
    ClickHouseRelation,
    ClickHouseSettings,
    DuckDBRelation,
    DuckDBSettings,
    PostgresRelation,
    PostgresSettings,
)
from .utils import parse_create_table_statement, render_statement
from typing import TYPE_CHECKING

import lazy_loader as lazy

if TYPE_CHECKING:
    from .adapters.clickhouse import ClickHouseAdapter
    from .adapters.duckdb import DuckDBAdapter
    from .adapters.postgres import PostgresAdapter

# TODO Replace with lazy keyword in Python 3.15+ https://docs.python.org/3.15/whatsnew/3.15.html#whatsnew315-lazy-imports
__getattr__, __dir__, _ = lazy.attach(
    __name__,
    submod_attrs={
        "adapters.clickhouse": ["ClickHouseAdapter"],
        "adapters.duckdb": ["DuckDBAdapter"],
        "adapters.postgres": ["PostgresAdapter"],
    },
)

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
    "parse_create_table_statement",
    "render_statement",
]
