from dw.adapters.clickhouse import ClickHouseAdapter
from dw.adapters.postgres import PostgresAdapter
from dw.peerdb import PeerDB
from dw.types import ClickHouseSettings, PostgresSettings
from sqlmodel import Table
from typing import Any, Generator, List

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


class BaseTest:
    @pytest.fixture(scope="class")
    def clickhouse_adapter(
        self, clickhouse_settings: ClickHouseSettings
    ) -> Generator[ClickHouseAdapter, Any, None]:
        yield ClickHouseAdapter(clickhouse_settings)

    @pytest.fixture(scope="class")
    def postgres_adapter(
        self, postgres_settings: PostgresSettings
    ) -> Generator[PostgresAdapter, Any, None]:
        yield PostgresAdapter(postgres_settings)

    @pytest.fixture(scope="function")
    def peerdb_config(
        self,
        postgres_settings: PostgresSettings,
        clickhouse_settings: ClickHouseSettings,
        monkeypatch,
    ) -> None:
        data = f"""
api_url: http://localhost:3000/api

settings:
  PEERDB_NULLABLE: "true"

peers:
  source:
    type: 3
    postgres_config:
      host: {postgres_settings.host}
      port: {postgres_settings.port}
      user: {postgres_settings.username}
      password: {postgres_settings.password}
      database: {postgres_settings.database}

  destination:
    type: 8
    clickhouse_config:
      host: {clickhouse_settings.host}
      http_port: {clickhouse_settings.http_port}
      tcp_port: {clickhouse_settings.tcp_port}
      user: {clickhouse_settings.username}
      password: {clickhouse_settings.password}
      database: {clickhouse_settings.database}

mirrors:
  +do_initial_snapshot: false
  +resync: false

  cdc_small:
    source_name: source
    destination_name: destination
    table_mappings:
    - source_table_identifier: public.table_1
      destination_table_identifier: table_1
    resync: true

  cdc_large:
    source_name: source
    destination_name: destination
    table_mappings:
    - source_table_identifier: public.table_2
      destination_table_identifier: table_2
    - source_table_identifier: public.table_3
      destination_table_identifier: table_3

publications:
  publication_1:
  - private.table_1
  - private.table_2
  publication_2:
  - private.table_3
"""
        config = yaml.safe_load(data)
        monkeypatch.setattr("dw.peerdb.PeerDB._load_config_yaml", lambda *args, **kwargs: config)


class TestEmptyConfig(BaseTest):
    @pytest.fixture(scope="function")
    def postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[List[Table], Any, None]:
        for table_def in table_defs:
            postgres_adapter.create_table(*table_def)

        table_names = [table_def[0] for table_def in table_defs]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    def test_func(self, monkeypatch):
        monkeypatch.setattr("dw.peerdb.PeerDB._load_config_yaml", lambda *args, **kwargs: {})
        expected = {
            "mirrors": {},
            "peers": {},
            "publication_schemas": [],
            "publications": {},
            "users": {},
        }

        assert PeerDB(None).config == expected


class TestSourcePeerMissingTable(BaseTest):
    @pytest.fixture(scope="function")
    def postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[List[Table], Any, None]:
        for table_def in table_defs[:1]:
            postgres_adapter.create_table(*table_def)

        table_names = [table_def[0] for table_def in table_defs[:1]]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    def test_func(self, postgres_tables: List[Table], peerdb_config: None):
        with pytest.raises(Exception) as exc:
            PeerDB(None)

        assert (
            str(exc.value) == "Source table 'public.table_2' not found in database of peer 'source'"
        )


class TestOK(BaseTest):
    @pytest.fixture(scope="function")
    def postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[List[Table], Any, None]:
        for table_def in table_defs:
            postgres_adapter.create_table(*table_def)

        table_names = [table_def[0] for table_def in table_defs]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    def test_func(self, postgres_tables: List[Table], peerdb_config: None):
        expected = {
            "api_url": "http://localhost:3000/api",
            "settings": {
                "PEERDB_NULLABLE": "true",
            },
            "peers": {
                "source": {
                    "type": 3,
                    "postgres_config": {
                        "host": "postgres",
                        "port": 5432,
                        "user": "postgres",
                        "password": "postgres",
                        "database": "test",
                    },
                    "name": "source",
                },
                "destination": {
                    "type": 8,
                    "clickhouse_config": {
                        "host": "clickhouse",
                        "http_port": 8123,
                        "tcp_port": 9000,
                        "user": "default",
                        "password": "default",
                        "database": "default",
                    },
                    "name": "destination",
                },
            },
            "mirrors": {
                "cdc_small": {
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
                    "flow_job_name": "cdc_small",
                },
                "cdc_large": {
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
                    "flow_job_name": "cdc_large",
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

        assert PeerDB(None).config == expected
