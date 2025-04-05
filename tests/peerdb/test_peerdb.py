from dw_lib import PeerDB, PostgresAdapter
from sqlmodel import Table
from typing import Any, Generator, List

import os
import pytest

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
            "api_url": "http://peerdb-ui:3000/api",
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
