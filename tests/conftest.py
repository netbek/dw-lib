from dw_lib import (
    ClickHouseAdapter,
    ClickHouseSettings,
    DuckDBAdapter,
    DuckDBSettings,
    PostgresAdapter,
    PostgresSettings,
)
from typing import Any, Generator

import os
import pytest


@pytest.fixture(scope="session")
def clickhouse_settings() -> Generator[ClickHouseSettings, Any, None]:
    yield ClickHouseSettings(
        host="localhost",
        http_port=18123,
        tcp_port=19000,
        username="default",
        password="default",
        database="default",
        secure=False,
        driver="http",
    )


@pytest.fixture(scope="session")
def duckdb_settings(pytestconfig) -> Generator[DuckDBSettings, Any, None]:
    yield DuckDBSettings(database=os.path.join(pytestconfig.rootpath, "tests/temp/test.duckdb"))


@pytest.fixture(scope="session")
def postgres_settings() -> Generator[PostgresSettings, Any, None]:
    yield PostgresSettings(
        host="localhost",
        port=15432,
        username="postgres",
        password="postgres",
        database="test",
    )


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    return os.path.join(str(pytestconfig.rootdir), "tests/docker-compose.database.yml")


@pytest.fixture(scope="session")
def docker_compose_project_name() -> str:
    return "dw-lib"  # Pin the project name to avoid creating multiple stacks


@pytest.fixture(scope="session")
def docker_setup():
    return ["down -v", "up --build -d"]  # Stop the stack before starting a new one


@pytest.fixture(scope="session")
def clickhouse_adapter(
    docker_services, clickhouse_settings: ClickHouseSettings
) -> Generator[ClickHouseAdapter, Any, None]:
    clickhouse_adapter = ClickHouseAdapter(clickhouse_settings)

    def is_responsive():
        try:
            with clickhouse_adapter.create_client() as client:
                client.query("select 1;")
            return True
        except Exception:
            return False

    docker_services.wait_until_responsive(timeout=10, pause=1, check=is_responsive)

    yield clickhouse_adapter


@pytest.fixture(scope="function")
def duckdb_adapter(duckdb_settings: DuckDBSettings) -> Generator[DuckDBAdapter, Any, None]:
    yield DuckDBAdapter(duckdb_settings)


@pytest.fixture(scope="session")
def postgres_adapter(
    docker_services, postgres_settings: PostgresSettings
) -> Generator[PostgresAdapter, Any, None]:
    postgres_adapter = PostgresAdapter(postgres_settings)

    def is_responsive():
        try:
            with postgres_adapter.create_client() as (conn, cur):
                cur.execute("select 1;")
            return True
        except Exception:
            return False

    docker_services.wait_until_responsive(timeout=10, pause=1, check=is_responsive)

    yield postgres_adapter
