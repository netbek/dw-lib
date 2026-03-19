from ..asserts import assert_count_equal
from ..conftest import PeerDBIntegrationTest
from datetime import datetime
from dw_lib.exceptions import (
    MirrorExistsException,
    MirrorNotFoundException,
    PeerExistsException,
    PeerNotFoundException,
    TableNotFoundException,
)
from dw_lib.peerdb import MirrorStatusResponse, PeerDB
from dw_lib.types import HttpUrl
from pathlib import Path
from sqlalchemy import make_url
from sqlmodel import Table

import pydash
import pytest


class TestLoadConfig(PeerDBIntegrationTest):
    def test_valid_config(self, all_postgres_tables: list[Table]):
        expected = {
            "peerdb_ui_url": HttpUrl("http://localhost:3000"),
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
                            "driver": "psycopg",
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
                            "ssh_config": None,
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
                            "driver": "http",
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
                            "certificate": None,
                            "private_key": None,
                            "root_ca": None,
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
                    "publication_name": "",
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
                    "publication_name": "",
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
            #         "table_identifiers": ["public.table_1", "public.table_2"],
            #     },
            #     {
            #         "name": "publication_2",
            #         "table_identifiers": ["public.table_3"],
            #     },
            # ],
        }

        config_file = Path(__file__).parent / "data" / "peerdb.clickhouse.yaml"
        assert PeerDB(config_file).config.model_dump(by_alias=True) == expected


class PeerDBClickHouseTest(PeerDBIntegrationTest):
    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        return Path(__file__).parent / "data" / "peerdb.clickhouse.yaml"


class TestDebug(PeerDBClickHouseTest):
    def test_ok(self, peerdb: PeerDB):
        actual = peerdb.debug()
        expected = {
            "API": {
                "URL": HttpUrl("http://localhost:3000/api"),
                "Connection test": "OK",
            },
            "Source peer": {
                "URL": make_url("postgresql+psycopg://postgres:postgres@localhost:25432/test"),
                "Connection test": "OK",
                "max_replication_slots >= 4": "OK",
                "max_wal_senders >= 1": "OK",
                "wal_level = logical": "OK",
            },
            "Destination peer": {
                "URL": make_url("clickhouse+http://default:default@localhost:28123/default"),
                "Connection test": "OK",
            },
        }
        assert actual == expected


class TestCreatePeer(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB):
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        # Tear down
        peerdb.drop_peer(peer.name)

    def test_existant_peer_raises_exception_if_exists_fail(self, peerdb: PeerDB):
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        with pytest.raises(PeerExistsException) as exc:
            peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()}, if_exists="fail")

        assert str(exc.value) == "Peer 'source' exists"

        # Tear down
        peerdb.drop_peer(peer.name)

    def test_existant_peer_if_exists_keep(self, peerdb: PeerDB):
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        response = peerdb.create_peer(
            {"name": peer.name, **peer.peerdb.model_dump()}, if_exists="keep"
        )
        assert response.message == "Kept peer 'source'"

        # Tear down
        peerdb.drop_peer(peer.name)


class TestDropPeer(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB):
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        peerdb.drop_peer(peer.name)
        assert peerdb.has_peer(peer.name) is False

    def test_non_existant_peer_raises_exception(self, peerdb: PeerDB):
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        with pytest.raises(PeerNotFoundException) as exc:
            peerdb.drop_peer(peer.name)

        assert str(exc.value) == "Peer 'source' not found"


class TestListPeers(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None):
        actual = [peer.model_dump() for peer in peerdb.list_peers().items]
        expected = [
            {"name": "source", "type": "POSTGRES"},
            {"name": "destination", "type": "CLICKHOUSE"},
        ]
        assert_count_equal(actual, expected)


class TestCreateMirror(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        # Tear down
        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)

    def test_non_existant_source_table_raises_exception(
        self, some_postgres_tables: list[Table], peerdb: PeerDB, peers: None
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_many")

        with pytest.raises(TableNotFoundException) as exc:
            peerdb.create_mirror(mirror.model_dump())

        assert (
            str(exc.value) == "Source table 'public.table_2' not found in database of peer 'source'"
        )
        assert peerdb.has_mirror(mirror.flow_job_name) is False

    def test_existant_mirror_raises_exception_if_exists_fail(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers: None
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_many")

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        with pytest.raises(MirrorExistsException) as exc:
            peerdb.create_mirror(mirror.model_dump(), if_exists="fail")

        assert str(exc.value) == "Mirror 'cdc_many' exists"

        # Tear down
        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)

    def test_existant_mirror_kept_if_exists_keep(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers: None
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_many")

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        response = peerdb.create_mirror(mirror.model_dump(), if_exists="keep")
        assert response.message == "Kept mirror 'cdc_many'"

        # Tear down
        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)


class TestDropMirror(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)
        assert peerdb.has_mirror(mirror.flow_job_name) is False

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestResyncMirror(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        response = peerdb.resync_mirror(mirror.flow_job_name)

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.resync_mirror(mirror.flow_job_name)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestPauseMirror(PeerDBClickHouseTest):
    def test_ok(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None, monkeypatch
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        # Mock the mirror status to STATUS_RUNNING so pause is allowed
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda flow_job_name: MirrorStatusResponse(
                createdAt=datetime.now(),
                currentFlowState="STATUS_RUNNING",
                flowJobName=flow_job_name,
            ),
        )

        # Prevent actual HTTP calls and waiting loop: simulate successful post and immediate paused state
        class _Response:
            status_code = 200

            def json(self):
                return {}

            def raise_for_status(self):
                return None

            text = ""

        monkeypatch.setattr("dw_lib.peerdb.httpx.post", lambda *a, **k: _Response())
        monkeypatch.setattr(peerdb, "wait_for_mirror_status", lambda *a, **k: "STATUS_PAUSED")

        response = peerdb.pause_mirror(mirror.flow_job_name)
        assert response.message == "Paused mirror 'cdc_one'"

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.pause_mirror(mirror.flow_job_name)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestResumeMirror(PeerDBClickHouseTest):
    def test_ok(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None, monkeypatch
    ):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        # Mock the mirror status to STATUS_PAUSED so resume is allowed
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda flow_job_name: MirrorStatusResponse(
                createdAt=datetime.now(),
                currentFlowState="STATUS_PAUSED",
                flowJobName=flow_job_name,
            ),
        )

        # Prevent actual HTTP calls and waiting loop: simulate successful post and immediate running state
        class _Response:
            status_code = 200

            def json(self):
                return {}

            def raise_for_status(self):
                return None

            text = ""

        monkeypatch.setattr("dw_lib.peerdb.httpx.post", lambda *a, **k: _Response())
        monkeypatch.setattr(peerdb, "wait_for_mirror_status", lambda *a, **k: "STATUS_RUNNING")

        response = peerdb.resume_mirror(mirror.flow_job_name)
        assert response.message == "Resumed mirror 'cdc_one'"

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.resume_mirror(mirror.flow_job_name)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestListMirrors(PeerDBClickHouseTest):
    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None):
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
