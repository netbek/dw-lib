from ..constants import PYTHON_RESERVED_WORDS
from ..types import ClickHouseDsn
from functools import lru_cache
from pydantic import PostgresDsn, TypeAdapter
from typing import Any

TYPE_ADAPTER_CLICKHOUSE_DSN = TypeAdapter(ClickHouseDsn)
TYPE_ADAPTER_POSTGRES_DSN = TypeAdapter(PostgresDsn)


@lru_cache
def is_python_reserved_word(value: str) -> bool:
    return value.lower() in PYTHON_RESERVED_WORDS


def validate_pydantic_clickhouse_dsn(value: Any) -> ClickHouseDsn:
    return TYPE_ADAPTER_CLICKHOUSE_DSN.validate_python(value)


def validate_pydantic_postgres_dsn(value: Any) -> PostgresDsn:
    return TYPE_ADAPTER_POSTGRES_DSN.validate_python(value)
