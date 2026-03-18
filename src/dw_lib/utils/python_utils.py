from ..constants import PYTHON_KEYWORDS
from functools import lru_cache
from pydantic import ClickHouseDsn, PostgresDsn, TypeAdapter

TYPE_ADAPTER_CLICKHOUSE_DSN = TypeAdapter(ClickHouseDsn)
TYPE_ADAPTER_POSTGRES_DSN = TypeAdapter(PostgresDsn)


@lru_cache
def is_python_keyword(value: str) -> bool:
    return value.lower() in PYTHON_KEYWORDS


def validate_clickhouse_dsn(value: str) -> ClickHouseDsn:
    return TYPE_ADAPTER_CLICKHOUSE_DSN.validate_python(value)


def validate_postgres_dsn(value: str) -> PostgresDsn:
    return TYPE_ADAPTER_POSTGRES_DSN.validate_python(value)
