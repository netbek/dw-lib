from ..asserts import assert_count_equal
from ..conftest import DatabaseTest, PeerDBTest
from collections.abc import Generator
from dw_lib.database.adapters import PostgresAdapter
from dw_lib.exceptions import EmptyConfigException, TableNotFoundException
from dw_lib.peerdb import PeerDB
from pathlib import Path
from sqlmodel import Table
from typing import Any

import pydash
import pytest
import time

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
    def all_postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[list[Table], Any, None]:
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

        with pytest.raises(EmptyConfigException):
            PeerDB(None)

    def test_valid_config(self, all_postgres_tables: list[Table]):
        expected = {
            "api_url": "http://localhost:3000/api",
            "settings": [
                {
                    "name": "PEERDB_NULLABLE",
                    "value": "true",
                }
            ],
            "peers": [
                {
                    "name": "source",
                    "adapter": {
                        "type": "postgres",
                        "settings": {
                            "host": "localhost",
                            "port": 25432,
                            "username": "postgres",
                            "password": "postgres",
                            "database": "test",
                            "schema": "public",
                        },
                    },
                    "peerdb": {
                        "type": 3,
                        "postgres_config": {
                            "host": "host.docker.internal",
                            "port": 25432,
                            "user": "postgres",
                            "password": "postgres",
                            "database": "test",
                        },
                    },
                },
                {
                    "name": "destination",
                    "adapter": {
                        "type": "clickhouse",
                        "settings": {
                            "host": "localhost",
                            "http_port": 28123,
                            "tcp_port": 29000,
                            "username": "default",
                            "password": "default",
                            "database": "default",
                            "secure": False,
                            "driver": None,
                        },
                    },
                    "peerdb": {
                        "type": 8,
                        "clickhouse_config": {
                            "host": "host.docker.internal",
                            "port": 29000,
                            "user": "default",
                            "database": "default",
                            "password": "default",
                            "disable_tls": True,
                        },
                    },
                },
            ],
            "mirrors": [
                {
                    "destination_name": "destination",
                    "do_initial_snapshot": False,
                    "flow_job_name": "cdc_one",
                    "idle_timeout_seconds": 60,
                    "initial_snapshot_only": False,
                    "max_batch_size": 1000000,
                    "resync": True,
                    "snapshot_max_parallel_workers": 4,
                    "snapshot_num_rows_per_partition": 1000000,
                    "snapshot_num_tables_in_parallel": 1,
                    "soft_delete_col_name": "_peerdb_is_deleted",
                    "source_name": "source",
                    "synced_at_col_name": "_peerdb_synced_at",
                    "table_mappings": [
                        {
                            "source_table_identifier": "public.table_1",
                            "destination_table_identifier": "table_1",
                        },
                    ],
                },
                {
                    "destination_name": "destination",
                    "do_initial_snapshot": False,
                    "flow_job_name": "cdc_many",
                    "idle_timeout_seconds": 60,
                    "initial_snapshot_only": False,
                    "max_batch_size": 1000000,
                    "resync": False,
                    "snapshot_max_parallel_workers": 4,
                    "snapshot_num_rows_per_partition": 1000000,
                    "snapshot_num_tables_in_parallel": 1,
                    "soft_delete_col_name": "_peerdb_is_deleted",
                    "source_name": "source",
                    "synced_at_col_name": "_peerdb_synced_at",
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
                },
            ],
            # "publications": [
            #     {
            #         "name": "publication_1",
            #         "table_identifiers": ["private.table_1", "private.table_2"],
            #     },
            #     {
            #         "name": "publication_2",
            #         "table_identifiers": ["private.table_3"],
            #     },
            # ],
            # "users": {},
            # "publication_schemas": ["private", "public"],
        }

        config_file = Path(__file__).parent / "data" / "peerdb.clickhouse.yaml"
        assert PeerDB(config_file).config.model_dump(by_alias=True) == expected


class TestIntegration(PeerDBTest):
    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        return Path(__file__).parent / "data" / "peerdb.clickhouse.yaml"

    @pytest.fixture(scope="function")
    def some_postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[list[Table], Any, None]:
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
    ) -> Generator[list[Table], Any, None]:
        for table_def in table_defs:
            postgres_adapter.create_table(*table_def)

        # Create all tables
        table_names = [table_def[0] for table_def in table_defs]
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

    def test_debug(self, peerdb: PeerDB):
        actual = peerdb.debug()
        expected = {
            "API": {
                "URL": "http://localhost:3000/api",
                "Connection test": "OK",
            },
            "Source peer": {
                "URL": "postgresql://postgres:***@localhost:25432/test",
                "Connection test": "OK",
                "max_replication_slots >= 4": "OK",
                "max_wal_senders >= 1": "OK",
                "wal_level = logical": "OK",
            },
            "Destination peer": {
                "URL": "clickhouse://default:***@localhost:28123/default",
                "Connection test": "OK",
            },
        }
        assert actual == expected

    def test_create_and_drop_peer(self, all_postgres_tables: list[Table], peerdb: PeerDB):
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        assert peerdb.has_peer(peer.name) is False

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        peerdb.drop_peer(peer.name)
        assert peerdb.has_peer(peer.name) is False

    def test_list_peers(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None
    ):
        actual = [peer.model_dump() for peer in peerdb.list_peers().items]
        expected = [
            {"name": "source", "type": "POSTGRES"},
            {"name": "destination", "type": "CLICKHOUSE"},
        ]
        assert_count_equal(actual, expected)

    def test_create_and_drop_mirror(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers: None
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        assert peerdb.has_mirror(mirror.flow_job_name) is False

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)
        assert peerdb.has_mirror(mirror.flow_job_name) is False

    def test_create_mirror_missing_table(
        self, some_postgres_tables: list[Table], peerdb: PeerDB, peers: None
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_many")

        assert peerdb.has_mirror(mirror.flow_job_name) is False

        with pytest.raises(TableNotFoundException) as exc:
            peerdb.create_mirror(mirror.model_dump())

        assert (
            str(exc.value) == "Source table 'public.table_2' not found in database of peer 'source'"
        )
        assert peerdb.has_mirror(mirror.flow_job_name) is False

    def test_list_mirrors(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None
    ):
        actual = [
            mirror.model_dump(
                include=[
                    "name",
                    "source_name",
                    "source_type",
                    "destination_name",
                    "destination_type",
                ]
            )
            for mirror in peerdb.list_mirrors().mirrors
        ]
        expected = [
            {
                "name": "cdc_one",
                "source_name": "source",
                "source_type": "POSTGRES",
                "destination_name": "destination",
                "destination_type": "CLICKHOUSE",
            },
            {
                "name": "cdc_many",
                "source_name": "source",
                "source_type": "POSTGRES",
                "destination_name": "destination",
                "destination_type": "CLICKHOUSE",
            },
        ]
        assert_count_equal(actual, expected)

    def test_pause_and_resume_mirror(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        assert peerdb.get_mirror_status(mirror.flow_job_name).current_flow_state == "STATUS_SETUP"

        response = peerdb.pause_mirror(mirror.flow_job_name)

        assert (
            response.message == "Not pausing mirror 'cdc_one' because its status is 'STATUS_SETUP'"
        )

        response = peerdb.resume_mirror(mirror.flow_job_name)

        assert (
            response.message == "Not resuming mirror 'cdc_one' because its status is 'STATUS_SETUP'"
        )
