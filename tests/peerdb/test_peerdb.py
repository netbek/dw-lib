from dw_lib import PeerDB, PostgresAdapter, PostgresSettings
from pytest_docker.plugin import get_docker_services, Services
from sqlmodel import Table
from typing import Any, Generator, Iterator, List, Union

import httpx
import os
import pydash
import pytest
import yaml

table_defs = [
    (
        "table_1",
        """
        create table table_1 (
            id bigint,
            username text,
            password text,
            age smallint,
            modified_at timestamp(6)
        );
        """,
    ),
    (
        "table_2",
        """
        create table table_2 (
            id bigint,
            longitude double precision,
            latitude double precision,
            is_secret boolean,
            modified_at timestamp(6)
        );
        """,
    ),
    (
        "table_3",
        """
        create table table_3 (
            id bigint,
            ts timestamp(6),
            modified_at timestamp(6)
        );
        """,
    ),
]


class TestLoadConfig:
    @pytest.fixture(scope="function")
    def some_postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[List[Table], Any, None]:
        for table_def in table_defs[:1]:
            postgres_adapter.create_table(*table_def)

        # Create some tables
        table_names = [table_def[0] for table_def in table_defs[:1]]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    @pytest.fixture(scope="function")
    def all_postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[List[Table], Any, None]:
        for table_def in table_defs:
            postgres_adapter.create_table(*table_def)

        # Create all tables
        table_names = [table_def[0] for table_def in table_defs]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    def test_empty_config(self, monkeypatch):
        monkeypatch.setattr("dw_lib.peerdb.PeerDB._load_config_data", lambda *args, **kwargs: {})
        expected = {
            "mirrors": {},
            "peers": {},
            "publication_schemas": [],
            "publications": {},
            "users": {},
        }

        assert PeerDB(None).config == expected

    def test_source_peer_missing_table(self, pytestconfig, some_postgres_tables: List[Table]):
        config_path = os.path.join(pytestconfig.rootpath, "tests/peerdb/fixtures/peerdb.yaml")
        with pytest.raises(Exception) as exc:
            PeerDB(config_path)

        assert (
            str(exc.value) == "Source table 'public.table_2' not found in database of peer 'source'"
        )

    def test_complete_config_and_source(self, pytestconfig, all_postgres_tables: List[Table]):
        expected = {
            "api_url": "http://localhost:3000/api",
            "settings": {
                "PEERDB_NULLABLE": "true",
            },
            "peers": {
                "source": {
                    "name": "source",
                    "adapter": {
                        "type": "postgres",
                        "settings": {
                            "host": "localhost",
                            "port": 15432,
                            "username": "postgres",
                            "password": "postgres",
                            "database": "test",
                        },
                    },
                    "peerdb": {
                        "type": 3,
                        "postgres_config": {
                            "host": "localhost",
                            "port": 15432,
                            "user": "postgres",
                            "password": "postgres",
                            "database": "test",
                        },
                    },
                },
                "destination": {
                    "name": "destination",
                    "adapter": {
                        "type": "clickhouse",
                        "settings": {
                            "host": "localhost",
                            "http_port": 18123,
                            "tcp_port": 19000,
                            "username": "default",
                            "password": "default",
                            "database": "default",
                            "secure": False,
                        },
                    },
                    "peerdb": {
                        "type": 8,
                        "clickhouse_config": {
                            "host": "localhost",
                            "port": 19000,
                            "user": "default",
                            "database": "default",
                            "password": "default",
                            "disable_tls": True,
                        },
                    },
                },
            },
            "mirrors": {
                "cdc_one": {
                    "source_name": "source",
                    "destination_name": "destination",
                    "table_mappings": [
                        {
                            "source_table_identifier": "public.table_1",
                            "destination_table_identifier": "table_1",
                        }
                    ],
                    "resync": True,
                    "do_initial_snapshot": False,
                    "flow_job_name": "cdc_one",
                },
                "cdc_many": {
                    "source_name": "source",
                    "destination_name": "destination",
                    "table_mappings": [
                        {
                            "source_table_identifier": "public.table_2",
                            "destination_table_identifier": "table_2",
                        },
                        {
                            "source_table_identifier": "public.table_3",
                            "destination_table_identifier": "table_3",
                        },
                    ],
                    "do_initial_snapshot": False,
                    "resync": False,
                    "flow_job_name": "cdc_many",
                },
            },
            "publications": {
                "publication_1": {
                    "name": "publication_1",
                    "table_identifiers": ["private.table_1", "private.table_2"],
                },
                "publication_2": {
                    "name": "publication_2",
                    "table_identifiers": ["private.table_3"],
                },
            },
            "users": {},
            "publication_schemas": ["private", "public"],
        }

        config_path = os.path.join(pytestconfig.rootpath, "tests/peerdb/fixtures/peerdb.yaml")
        assert PeerDB(config_path).config == expected


class PeerDBTest:
    @pytest.fixture(scope="function")
    def docker_compose_file(self, pytestconfig):
        return [
            os.path.join(str(pytestconfig.rootdir), "tests/docker-compose.database.yml"),
            os.path.join(str(pytestconfig.rootdir), "tests/docker-compose.peerdb.yml"),
        ]

    @pytest.fixture(scope="function")
    def docker_compose_project_name(self) -> str:
        return "dw-lib"  # Pin the project name to avoid creating multiple stacks

    @pytest.fixture(scope="function")
    def docker_setup(self):
        return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="function")
    def docker_services(
        self,
        docker_compose_command: str,
        docker_compose_file: Union[List[str], str],
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

    @pytest.fixture(scope="function")
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

        docker_services.wait_until_responsive(timeout=10, pause=1, check=is_responsive)

        yield postgres_adapter

    @pytest.fixture(scope="function")
    def peerdb(self, pytestconfig, docker_services) -> Generator[str, Any, None]:
        config_path = os.path.join(pytestconfig.rootpath, "tests/peerdb/fixtures/peerdb.yaml")

        with open(config_path) as fp:
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

        docker_services.wait_until_responsive(timeout=10, pause=1, check=is_responsive)

        yield PeerDB(config_path)


# class TestSettings(PeerDBTest):
#     @pytest.fixture(scope="function")
#     def postgres_tables(
#         self, postgres_adapter: PostgresAdapter
#     ) -> Generator[List[Table], Any, None]:
#         for table_def in table_defs:
#             postgres_adapter.create_table(*table_def)

#         # Create all tables
#         table_names = [table_def[0] for table_def in table_defs]
#         tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

#         yield tables

#         for table_name in table_names:
#             postgres_adapter.drop_table(table_name)

#     def test_get_and_update_settings(self, postgres_tables: List[Table], peerdb: PeerDB):
#         settings = peerdb.list_settings()
#         assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value is None

#         peerdb.update_settings({"PEERDB_NULLABLE": "false"})
#         settings = peerdb.list_settings()
#         assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "false"

#         peerdb.update_settings({"PEERDB_NULLABLE": "true"})
#         settings = peerdb.list_settings()
#         assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "true"
