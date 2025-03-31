from dw_lib import ClickHouseSettings, DuckDBSettings, IcebergSettings, PostgresSettings
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
def iceberg_settings() -> Generator[IcebergSettings, Any, None]:
    yield IcebergSettings(
        type="sql",
        uri="postgresql+psycopg2://iceberg:iceberg@postgres:5432/iceberg",
        warehouse="s3://iceberg/",
        s3_endpoint="http://minio:9000",
        s3_access_key_id="admin",
        s3_secret_access_key="password",
        s3_region="us-east-1",
    )


@pytest.fixture(scope="session")
def postgres_settings() -> Generator[PostgresSettings, Any, None]:
    yield PostgresSettings(
        host="postgres",
        port=5432,
        username="postgres",
        password="postgres",
        database="test",
    )
