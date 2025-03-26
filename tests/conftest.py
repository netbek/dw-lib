from dw import ClickHouseSettings, PostgresSettings, DuckDBSettings
from typing import Any, Generator
import pytest


@pytest.fixture(scope="session")
def clickhouse_settings() -> Generator[ClickHouseSettings, Any, None]:
    yield ClickHouseSettings(
        host="clickhouse",
        http_port=8123,
        tcp_port=9000,
        username="default",
        password="default",
        database="default",
        secure=False,
        driver="http",
    )


@pytest.fixture(scope="session")
def duckdb_settings() -> Generator[DuckDBSettings, Any, None]:
    yield DuckDBSettings(database="/app/temp/test.duckdb")


@pytest.fixture(scope="session")
def postgres_settings() -> Generator[PostgresSettings, Any, None]:
    yield PostgresSettings(
        host="postgres",
        port=5432,
        username="postgres",
        password="postgres",
        database="test",
    )
