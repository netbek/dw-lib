from ..asserts import assert_count_equal
from ..conftest import PeerDBTest
from dw_lib import PeerDB, PostgresAdapter
from dw_lib.types import PostgresSettings
from sqlmodel import Table
from typing import Any, Generator, List

import copy
import os
import pydash
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


class TestLoadConfig(PeerDBTest):
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
                            "port": 25432,
                            "username": "postgres",
                            "password": "postgres",
                            "database": "test",
                        },
                    },
                    "peerdb": {
                        "type": 3,
                        "postgres_config": {
                            "host": "localhost",
                            "port": 25432,
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
                            "http_port": 28123,
                            "tcp_port": 29000,
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
                            "port": 29000,
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


# class TestInspect:
#     @pytest.fixture(scope="function")
#     def postgres_adapter(self) -> Generator[PostgresAdapter, Any, None]:
#         postgres_settings = PostgresSettings(
#             host="localhost",
#             port=25432,
#             username="postgres",
#             password="postgres",
#             database="test",
#         )
#         postgres_adapter = PostgresAdapter(postgres_settings)

#         yield postgres_adapter

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

#     def test_inspect(self, pytestconfig, postgres_tables):
#         config_path = os.path.join(pytestconfig.rootpath, "tests/peerdb/fixtures/peerdb.yaml")

#         peerdb = PeerDB(config_path)

#         peerdb._config["peers"]["source"]["peerdb"]["postgres_config"]["host"] = (
#             "host.docker.internal"
#         )
#         peerdb._config["peers"]["destination"]["peerdb"]["clickhouse_config"]["host"] = (
#             "host.docker.internal"
#         )

#         for peer in peerdb.config["peers"].values():
#             peerdb.create_peer({"name": peer["name"], **peer["peerdb"]})

#         for mirror in peerdb.config["mirrors"].values():
#             peerdb.create_mirror(mirror)

#         # print(peerdb.list_mirrors())

#         for mirror in peerdb.config["mirrors"].values():
#             peerdb.drop_mirror(mirror["flow_job_name"])

#         for peer in peerdb.config["peers"].values():
#             peerdb.drop_peer(peer["name"])


class TestIntegration(PeerDBTest):
    @pytest.fixture(scope="function")
    def postgres_tables(
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

    @pytest.fixture(scope="function")
    def peers_and_mirrors(self, peerdb: PeerDB) -> Generator[None, Any, None]:
        for peer in peerdb.config["peers"].values():
            peerdb.create_peer({"name": peer["name"], **peer["peerdb"]})

        for mirror in peerdb.config["mirrors"].values():
            peerdb.create_mirror(mirror)

        yield None

        for mirror in peerdb.config["mirrors"].values():
            peerdb.drop_mirror(mirror["flow_job_name"])

        for peer in peerdb.config["peers"].values():
            peerdb.drop_peer(peer["name"])

    def test_get_and_update_settings(self, postgres_tables: List[Table], peerdb: PeerDB):
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value is None

        peerdb.update_settings({"PEERDB_NULLABLE": "false"})
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "false"

        peerdb.update_settings({"PEERDB_NULLABLE": "true"})
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "true"

    # def test_create_and_drop_peer(self, postgres_tables: List[Table], peerdb: PeerDB):
    #     peer = copy.deepcopy(peerdb.config["peers"]["source"])
    #     peer = {"name": peer["name"], **peer["peerdb"]}

    #     assert peerdb.has_peer(peer) is False

    #     peerdb.create_peer(peer)
    #     assert peerdb.has_peer(peer) is True

    #     peerdb.drop_peer(peer['name'])
    #     assert peerdb.has_peer(peer) is False

    def test_list_peers(
        self, postgres_tables: List[Table], peerdb: PeerDB, peers_and_mirrors: None
    ):
        actual = [peer.model_dump() for peer in peerdb.list_peers().items]
        expected = [
            {"name": "source", "type": "POSTGRES"},
            {"name": "destination", "type": "CLICKHOUSE"},
        ]
        assert_count_equal(actual, expected)

    # def test_create_and_drop_mirror(
    #     self, postgres_tables: List[Table], peerdb: PeerDB, peers: List[PeerDBPeer]
    # ):
    #     mirror = peerdb.config["mirrors"]["cdc_one"]

    #     assert peerdb.has_mirror(mirror) is False

    #     peerdb.create_mirror(mirror)
    #     assert peerdb.has_mirror(mirror) is True

    #     peerdb.drop_mirror(mirror["flow_job_name"])
    #     assert peerdb.has_mirror(mirror) is False

    def test_list_mirrors(
        self, postgres_tables: List[Table], peerdb: PeerDB, peers_and_mirrors: None
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
