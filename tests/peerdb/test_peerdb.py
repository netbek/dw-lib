from ..fixtures.database import DatabaseTest
from dw_lib import PeerDB, PostgresAdapter
from sqlmodel import Table
from typing import Any, Generator, List

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


class TestLoadConfig(DatabaseTest):
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

    def test_source_peer_missing_table(self, some_postgres_tables: List[Table]):
        with pytest.raises(Exception) as exc:
            PeerDB("/app/tests/peerdb/fixtures/peerdb.yaml")

        assert (
            str(exc.value) == "Source table 'public.table_2' not found in database of peer 'source'"
        )

    def test_complete(self, all_postgres_tables: List[Table]):
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
                            "host": "postgres",
                            "port": 5432,
                            "username": "postgres",
                            "password": "postgres",
                            "database": "test",
                        },
                    },
                    "peerdb": {
                        "type": 3,
                        "postgres_config": {
                            "host": "postgres",
                            "port": 5432,
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
                            "host": "clickhouse",
                            "http_port": 8123,
                            "tcp_port": 9000,
                            "username": "default",
                            "password": "default",
                            "database": "default",
                            "secure": False,
                        },
                    },
                    "peerdb": {
                        "type": 8,
                        "clickhouse_config": {
                            "host": "clickhouse",
                            "port": 9000,
                            "user": "default",
                            "database": "default",
                            "password": "default",
                            "disable_tls": True,
                        },
                    },
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

        assert PeerDB("/app/tests/peerdb/fixtures/peerdb.yaml").config == expected
