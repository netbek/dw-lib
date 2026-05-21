from .utils import render_statement
from importlib import import_module
from typing import TYPE_CHECKING

import threading

if TYPE_CHECKING:
    from .adapters.clickhouse import ClickHouseAdapter, ClickHouseRelation, ClickHouseSettings
    from .adapters.duckdb import DuckDBAdapter, DuckDBRelation, DuckDBSettings
    from .adapters.postgres import PostgresAdapter, PostgresRelation, PostgresSettings

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

_LAZY_IMPORTS = {
    "ClickHouseAdapter": ("dw_lib.database.adapters.clickhouse", "ClickHouseAdapter"),
    "ClickHouseRelation": ("dw_lib.database.adapters.clickhouse", "ClickHouseRelation"),
    "ClickHouseSettings": ("dw_lib.database.adapters.clickhouse", "ClickHouseSettings"),
    "DuckDBAdapter": ("dw_lib.database.adapters.duckdb", "DuckDBAdapter"),
    "DuckDBRelation": ("dw_lib.database.adapters.duckdb", "DuckDBRelation"),
    "DuckDBSettings": ("dw_lib.database.adapters.duckdb", "DuckDBSettings"),
    "PostgresAdapter": ("dw_lib.database.adapters.postgres", "PostgresAdapter"),
    "PostgresRelation": ("dw_lib.database.adapters.postgres", "PostgresRelation"),
    "PostgresSettings": ("dw_lib.database.adapters.postgres", "PostgresSettings"),
}

_lock = threading.Lock()


def _import_and_cache(name: str):
    if name in globals():
        return globals()[name]

    with _lock:
        if name in globals():
            return globals()[name]

        module_name, attr_name = _LAZY_IMPORTS[name]

        module = import_module(module_name)
        value = getattr(module, attr_name)

        globals()[name] = value
        return value


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        return _import_and_cache(name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))
