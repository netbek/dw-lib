from ..constants import PYTHON_RESERVED_WORDS
from functools import lru_cache
from pydantic import ClickHouseDsn, PostgresDsn, TypeAdapter, UrlConstraints
from typing import Any


# TODO Remove this class in favour of ClickHouseDsn after "clickhousedb+connect" has been added
class CustomClickHouseDsn(ClickHouseDsn):
    _constraints = UrlConstraints(
        allowed_schemes=ClickHouseDsn._constraints.allowed_schemes + ["clickhousedb+connect"],
        default_host=ClickHouseDsn._constraints.default_host,
        default_port=ClickHouseDsn._constraints.default_port,
    )


TYPE_ADAPTER_CLICKHOUSE_DSN = TypeAdapter(CustomClickHouseDsn)
TYPE_ADAPTER_POSTGRES_DSN = TypeAdapter(PostgresDsn)


@lru_cache
def is_python_reserved_word(value: str) -> bool:
    return value.lower() in PYTHON_RESERVED_WORDS


def validate_pydantic_clickhouse_dsn(value: Any) -> CustomClickHouseDsn:
    return TYPE_ADAPTER_CLICKHOUSE_DSN.validate_python(value)


def validate_pydantic_postgres_dsn(value: Any) -> PostgresDsn:
    return TYPE_ADAPTER_POSTGRES_DSN.validate_python(value)
