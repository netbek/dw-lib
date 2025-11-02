from collections.abc import Generator, Iterator
from dw_lib.cloud.adapters import S3Adapter
from dw_lib.database.adapters import ClickHouseAdapter, DuckDBAdapter, PostgresAdapter
from dw_lib.peerdb import PeerDB
from dw_lib.streamer import Streamer
from dw_lib.types import ClickHouseSettings, DuckDBSettings, PostgresSettings, S3Settings
from pathlib import Path
from pytest_docker.plugin import get_docker_services, Services
from typing import Any

import httpx
import os
import pytest
import yaml


class DatabaseTest:
    @pytest.fixture(scope="module")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.database.yml"

    @pytest.fixture(scope="module")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-database"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="module")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="module")
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

    @pytest.fixture(scope="module")
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
    @pytest.fixture(scope="module")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.peerdb.yml"

    @pytest.fixture(scope="module")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-peerdb"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="module")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="module")
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

    @pytest.fixture(scope="module")
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
                return postgres_adapter.can_connect()
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


class StreamerTest:
    @pytest.fixture(scope="module")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.streamer.yml"

    @pytest.fixture(scope="module")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-streamer"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="module")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    # @pytest.fixture(scope="module")
    # def clickhouse_adapter(self, docker_services) -> Generator[ClickHouseAdapter, Any, None]:
    #     clickhouse_settings = ClickHouseSettings(
    #         host="localhost",
    #         http_port=28123,
    #         tcp_port=29000,
    #         username="default",
    #         password="default",
    #         database="default",
    #         secure=False,
    #         driver="http",
    #     )
    #     clickhouse_adapter = ClickHouseAdapter(clickhouse_settings)

    #     def is_responsive():
    #         try:
    #             return clickhouse_adapter.can_connect()
    #         except Exception:
    #             return False

    #     docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

    #     yield clickhouse_adapter

    @pytest.fixture(scope="module")
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
                return postgres_adapter.can_connect()
            except Exception:
                return False

        docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        yield postgres_adapter

    @pytest.fixture(scope="module")
    def s3_adapter(self, docker_services) -> Generator[S3Adapter, Any, None]:
        s3_settings = S3Settings(
            key_id="admin",
            secret="password",
            region="us-east-1",
            endpoint="localhost:28950",
            use_ssl=False,
            bucket="streamer",
        )
        s3_adapter = S3Adapter(s3_settings)

        docker_services.wait_until_responsive(
            check=lambda: s3_adapter.can_connect(), timeout=10, pause=1
        )

        yield s3_adapter

    @pytest.fixture(scope="function")
    def streamer(
        self,
        streamer_config_path: str,
        # clickhouse_adapter: ClickHouseAdapter,
        postgres_adapter: PostgresAdapter,
        s3_adapter: S3Adapter,
    ) -> Generator[Streamer, Any, None]:
        yield Streamer(streamer_config_path)
