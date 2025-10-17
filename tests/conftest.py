from collections.abc import Generator, Iterator
from dw_lib.database.adapters import ClickHouseAdapter, DuckDBAdapter, PostgresAdapter
from dw_lib.peerdb import PeerDB
from dw_lib.types import ClickHouseSettings, DuckDBSettings, PostgresSettings
from pathlib import Path
from pytest_docker.plugin import get_docker_services, Services
from typing import Any

import httpx
import os
import pytest
import yaml


class DatabaseTest:
    @pytest.fixture(scope="session")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.database.yml"

    @pytest.fixture(scope="session")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-database"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="session")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="session")
    def clickhouse_adapter(self, docker_services) -> Generator[ClickHouseAdapter, Any, None]:
        clickhouse_settings = ClickHouseSettings(
            host="localhost",
            http_port=18123,
            tcp_port=19000,
            username="default",
            password="default",
            database="default",
            secure=False,
            driver="http",
        )
        clickhouse_adapter = ClickHouseAdapter(clickhouse_settings)

        def is_responsive():
            try:
                with clickhouse_adapter.create_client() as client:
                    client.query("select 1;")
                return True
            except Exception:
                return False

        docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        yield clickhouse_adapter

    @pytest.fixture(scope="function")
    def duckdb_adapter(self) -> Generator[DuckDBAdapter, Any, None]:
        file = Path(__file__).parent / "temp" / "test.duckdb"
        duckdb_settings = DuckDBSettings(database=file)
        duckdb_adapter = DuckDBAdapter(duckdb_settings)

        yield duckdb_adapter

    @pytest.fixture(scope="session")
    def postgres_adapter(self, docker_services) -> Generator[PostgresAdapter, Any, None]:
        postgres_settings = PostgresSettings(
            host="localhost",
            port=15432,
            username="postgres",
            password="postgres",
            database="test",
        )
        postgres_adapter = PostgresAdapter(postgres_settings)

        def is_responsive():
            try:
                with postgres_adapter.create_client() as (conn, cur):
                    cur.execute("select 1;")
                return True
            except Exception:
                return False

        docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        yield postgres_adapter


class PeerDBTest:
    @pytest.fixture(scope="session")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.peerdb.yml"

    @pytest.fixture(scope="session")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-peerdb"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="session")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="session")
    def docker_services(
        self,
        docker_compose_command: str,
        docker_compose_file: list[str] | str,
        docker_compose_project_name: str,
        docker_setup: str,
        docker_cleanup: str,
    ) -> Iterator[Services]:
        with get_docker_services(
            docker_compose_command,
            docker_compose_file,
            docker_compose_project_name,
            docker_setup,
            docker_cleanup,
        ) as docker_service:
            yield docker_service

    @pytest.fixture(scope="session")
    def postgres_adapter(self, docker_services) -> Generator[PostgresAdapter, Any, None]:
        postgres_settings = PostgresSettings(
            host="localhost",
            port=25432,
            username="postgres",
            password="postgres",
            database="test",
        )
        postgres_adapter = PostgresAdapter(postgres_settings)

        def is_responsive():
            try:
                with postgres_adapter.create_client() as (conn, cur):
                    cur.execute("select 1;")
                return True
            except Exception:
                return False

        docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        yield postgres_adapter

    @pytest.fixture(scope="function")
    def peerdb(self, peerdb_config_path: str, docker_services) -> Generator[str, Any, None]:
        with open(peerdb_config_path) as fp:
            peerdb_config = yaml.safe_load(fp)

        url = os.path.join(peerdb_config["api_url"], "v1/instance/info")

        def is_responsive():
            try:
                response = httpx.get(url, headers={"Content-Type": "application/json"})
                if response.status_code == 200 and response.json() == {
                    "status": "INSTANCE_STATUS_READY"
                }:
                    return True
            except Exception:
                return False

        docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        peerdb = PeerDB(peerdb_config_path)

        yield peerdb
