from ..constants import PYTHON_RESERVED_WORDS
from functools import lru_cache
from pydantic import ClickHouseDsn, HttpUrl, PostgresDsn, TypeAdapter
from sqlalchemy import URL
from typing import Any

TYPE_ADAPTER_CLICKHOUSE_DSN = TypeAdapter(ClickHouseDsn)
TYPE_ADAPTER_POSTGRES_DSN = TypeAdapter(PostgresDsn)


@lru_cache
def is_python_reserved_word(value: str) -> bool:
    return value.lower() in PYTHON_RESERVED_WORDS


def is_pydantic_http_url(value: Any) -> bool:
    return isinstance(value, HttpUrl)


def is_pydantic_clickhouse_dsn(value: Any) -> bool:
    return isinstance(value, ClickHouseDsn)


def is_pydantic_postgres_dsn(value: Any) -> bool:
    return isinstance(value, PostgresDsn)


def is_sqlalchemy_url(value: Any) -> bool:
    return isinstance(value, URL)


def validate_pydantic_clickhouse_dsn(value: Any) -> ClickHouseDsn:
    return TYPE_ADAPTER_CLICKHOUSE_DSN.validate_python(value)


def validate_pydantic_postgres_dsn(value: Any) -> PostgresDsn:
    return TYPE_ADAPTER_POSTGRES_DSN.validate_python(value)
