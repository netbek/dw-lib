from clickhouse_sqlalchemy import engines, types
from collections.abc import Generator, Iterator
from dw_lib.cloud.adapters import S3Adapter
from dw_lib.database.adapters import ClickHouseAdapter, DuckDBAdapter, PostgresAdapter
from dw_lib.loader import Loader
from dw_lib.peerdb import PeerDB
from dw_lib.types import ClickHouseSettings, DuckDBSettings, HttpUrl, PostgresSettings, S3Settings
from pathlib import Path
from pytest_docker.plugin import get_docker_services, Services
from ruamel.yaml import YAML
from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Table
from typing import Any

import os
import pytest
import requests


class TableWithoutSchema(SQLModel, table=True):
    __tablename__ = "table_without_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            index_granularity=8192,
        ),
    )


class TableWithSchema(SQLModel, table=True):
    __tablename__ = "table_with_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            index_granularity=8192,
        ),
        {"schema": "analytics"},
    )


class ViewWithoutSchema(SQLModel):
    __tablename__ = "view_without_schema"
    __sql__ = """
    SELECT 42 AS id
    """


class ViewWithSchema(SQLModel):
    __tablename__ = "view_with_schema"
    __sql__ = """
    SELECT 42 AS id
    """
    __table_args__ = {"schema": "analytics"}


class DatabaseTest:
    @pytest.fixture(scope="module")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.database.yml"

    @pytest.fixture(scope="module")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-database"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="module")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build --wait"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="module")
    def clickhouse_settings(self) -> ClickHouseSettings:
        return ClickHouseSettings(
            host="localhost",
            http_port=18123,
            tcp_port=19000,
            username="default",
            password="default",
            database="default",
            driver="http",
        )

    @pytest.fixture(scope="module")
    def clickhouse_adapter(
        self, docker_services, clickhouse_settings: ClickHouseSettings
    ) -> Generator[ClickHouseAdapter, Any, None]:
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
    def duckdb_settings(self) -> DuckDBSettings:
        file = Path(__file__).parent / "temp" / "test.duckdb"
        return DuckDBSettings(database=file)

    @pytest.fixture(scope="function")
    def duckdb_adapter(
        self, duckdb_settings: DuckDBSettings
    ) -> Generator[DuckDBAdapter, Any, None]:
        duckdb_adapter = DuckDBAdapter(duckdb_settings)
        yield duckdb_adapter

    @pytest.fixture(scope="module")
    def postgres_settings(self) -> PostgresSettings:
        return PostgresSettings(
            host="localhost",
            port=15432,
            username="postgres",
            password="postgres",
            database="test",
            driver="psycopg2",
        )

    @pytest.fixture(scope="module")
    def postgres_adapter(
        self, docker_services, postgres_settings: PostgresSettings
    ) -> Generator[PostgresAdapter, Any, None]:
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

    # @pytest.fixture(scope="module")
    # def victoria_traces(self, docker_services) -> Generator[str, Any, None]:
    #     url = "http://localhost:20428"

    #     def is_responsive():
    #         try:
    #             response = requests.get(url)
    #             return response.status_code == 200
    #         except Exception:
    #             return False

    #     docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

    #     yield url


class PeerDBTest:
    @pytest.fixture(scope="module", autouse=True)
    def set_env(self):
        # Source: https://github.com/PeerDB-io/peerdb/blob/v0.36.9/docker-compose.yml
        os.environ.update(
            {
                "MINIO_IMAGE": "minio/minio:RELEASE.2025-09-07T16-13-09Z",
                "PEERDB_FLOW_API_IMAGE": "ghcr.io/peerdb-io/flow-api:stable-v0.36.7",
                "PEERDB_FLOW_SNAPSHOT_WORKER_IMAGE": "ghcr.io/peerdb-io/flow-snapshot-worker:stable-v0.36.7",
                "PEERDB_FLOW_WORKER_IMAGE": "ghcr.io/peerdb-io/flow-worker:stable-v0.36.7",
                "PEERDB_SERVER_IMAGE": "ghcr.io/peerdb-io/peerdb-server:stable-v0.36.7",
                "PEERDB_UI_IMAGE": "ghcr.io/peerdb-io/peerdb-ui:stable-v0.36.7",
                "POSTGRES_IMAGE": "postgres:18.3-alpine3.23",
                "TEMPORAL_ADMIN_TOOLS_IMAGE": "temporalio/admin-tools:1.25.2-tctl-1.18.1-cli-1.1.1",
                "TEMPORAL_AUTO_SETUP_IMAGE": "temporalio/auto-setup:1.29.4.1",
                "TEMPORAL_UI_IMAGE": "temporalio/ui:2.45.4",
            }
        )

    @pytest.fixture(scope="module")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.peerdb.yml"

    @pytest.fixture(scope="module")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-peerdb"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="module")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build --wait"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="module")
    def docker_services(
        self,
        docker_compose_command: str,
        docker_compose_file: list[str] | str,
        docker_compose_project_name: str,
        docker_setup: list[str] | str,
        docker_cleanup: list[str] | str,
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
            driver="psycopg2",
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
    def peerdb(
        self, request, peerdb_config_path: Path, docker_services
    ) -> Generator[PeerDB, Any, None]:
        skip_wait = request.node.get_closest_marker("docker_skip_wait_until_responsive")

        if not skip_wait:
            yaml = YAML(typ="safe", pure=True)
            peerdb_config = yaml.load(peerdb_config_path)

            url = HttpUrl(peerdb_config["peerdb_ui_url"]).join("api/v1/instance/info")

            def is_responsive():
                try:
                    response = requests.get(str(url), headers={"Content-Type": "application/json"})
                    if response.status_code == 200 and response.json() == {
                        "status": "INSTANCE_STATUS_READY"
                    }:
                        return True
                except Exception:
                    return False

            docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        peerdb = PeerDB(peerdb_config_path)

        yield peerdb


class PeerDBIntegrationTest(PeerDBTest):
    @pytest.fixture(scope="function")
    def table_defs(self) -> list[dict[str, str]]:
        return [
            {
                "table": "table_1",
                "create_statement": """
                    create table table_1 (
                        id bigint,
                        username text,
                        password text,
                        age smallint,
                        modified_at timestamp(6)
                    );
                """,
            },
            {
                "table": "table_2",
                "create_statement": """
                    create table table_2 (
                        id bigint,
                        longitude double precision,
                        latitude double precision,
                        is_secret boolean,
                        modified_at timestamp(6)
                    );
                """,
            },
            {
                "table": "table_3",
                "create_statement": """
                    create table table_3 (
                        id bigint,
                        ts timestamp(6),
                        modified_at timestamp(6)
                    );
                """,
            },
        ]

    @pytest.fixture(scope="function")
    def some_postgres_tables(
        self, postgres_adapter: PostgresAdapter, table_defs: list[dict[str, str]]
    ) -> Generator[list[Table], Any, None]:
        for table_def in table_defs[:1]:
            postgres_adapter.create_table(
                table=table_def["table"], statement=table_def["create_statement"]
            )

        # Create some tables
        table_names = [table_def["table"] for table_def in table_defs[:1]]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    @pytest.fixture(scope="function")
    def all_postgres_tables(
        self, postgres_adapter: PostgresAdapter, table_defs: list[dict[str, str]]
    ) -> Generator[list[Table], Any, None]:
        for table_def in table_defs:
            postgres_adapter.create_table(
                table=table_def["table"], statement=table_def["create_statement"]
            )

        # Create all tables
        table_names = [table_def["table"] for table_def in table_defs]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    @pytest.fixture(scope="function")
    def peers(self, peerdb: PeerDB) -> Generator[None, Any, None]:
        for peer in peerdb.config.peers:
            peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})

        yield None

        for peer in peerdb.config.peers:
            peerdb.drop_peer(peer.name, drop_mirrors=True, drop_destination_tables=True)

    @pytest.fixture(scope="function")
    def peers_and_mirrors(self, peerdb: PeerDB) -> Generator[None, Any, None]:
        for peer in peerdb.config.peers:
            peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})

        for mirror in peerdb.config.mirrors:
            peerdb.create_mirror(mirror.model_dump())

        yield None

        for peer in peerdb.config.peers:
            peerdb.drop_peer(peer.name, drop_mirrors=True, drop_destination_tables=True)


class LoaderTest:
    @pytest.fixture(scope="module")
    def docker_compose_file(self) -> Path:
        return Path(__file__).parent / "docker-compose.loader.yml"

    @pytest.fixture(scope="module")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-loader"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="module")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build --wait"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="module")
    def postgres_adapter(self, docker_services) -> Generator[PostgresAdapter, Any, None]:
        postgres_settings = PostgresSettings(
            host="localhost",
            port=25432,
            username="postgres",
            password="postgres",
            database="test",
            driver="psycopg2",
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
            bucket="loader",
        )
        s3_adapter = S3Adapter(s3_settings)

        docker_services.wait_until_responsive(
            check=lambda: s3_adapter.can_connect(), timeout=10, pause=1
        )

        yield s3_adapter

    @pytest.fixture(scope="function")
    def loader(
        self,
        loader_config_path: str,
        # clickhouse_adapter: ClickHouseAdapter,
        postgres_adapter: PostgresAdapter,
        s3_adapter: S3Adapter,
    ) -> Generator[Loader, Any, None]:
        yield Loader(loader_config_path)
