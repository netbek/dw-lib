from ..asserts import assert_count_equal
from ..conftest import PeerDBIntegrationTest
from .conftest import table_kwargs
from collections.abc import Generator
from dw_lib.database import ClickHouseAdapter, ClickHouseSettings
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
from sqlalchemy import make_url, Table
from typing import Any

import datetime
import pydash
import pytest


class TestLoadConfig(PeerDBIntegrationTest):
    """Tests for `PeerDB` config parsing."""

    def test_valid_config(self, all_postgres_tables: list[Table]):
        """Verify the ClickHouse YAML config parses to expected peers and mirrors."""
        expected = {
            "peerdb_ui_url": HttpUrl("http://localhost:3000"),
            "operation_timeout": 30,
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
                            "driver": "psycopg2",
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
                            "port": 28123,
                            "username": "default",
                            "password": "default",
                            "database": "default",
                            "driver": "connect",
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
                            "exclude": None,
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
                            "exclude": ["large_column", "very_large_column"],
                        },
                        {
                            "source_table_identifier": "public.table_3",
                            "destination_table_identifier": "table_3",
                            "exclude": None,
                        },
                    ],
                },
            ],
        }

        config_file = Path(__file__).parent / "data" / "peerdb.clickhouse.yaml"
        assert PeerDB(config_file).config.model_dump(by_alias=True) == expected


class PeerDBClickHouseTest(PeerDBIntegrationTest):
    """Shared context for ClickHouse-backed PeerDB integration tests."""

    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        """Provide the ClickHouse PeerDB config path."""
        return Path(__file__).parent / "data" / "peerdb.clickhouse.yaml"

    @pytest.fixture(scope="module")
    def destination_adapter(self, docker_services) -> Generator[ClickHouseAdapter, Any]:
        """Provide the ClickHouse destination adapter."""
        clickhouse_settings = ClickHouseSettings(
            host="localhost",
            port=28123,
            username="default",
            password="default",
            database="default",
            driver="connect",
        )
        clickhouse_adapter = ClickHouseAdapter(clickhouse_settings)

        def is_responsive():
            try:
                with clickhouse_adapter.create_client() as client:
                    client.query("select 1;")
                return True
            except Exception:  # noqa: BLE001
                return False

        docker_services.wait_until_responsive(check=is_responsive, timeout=10, pause=1)

        yield clickhouse_adapter


class TestDebug(PeerDBClickHouseTest):
    """Tests for `PeerDB.debug` connection reporting."""

    def test_ok(self, peerdb: PeerDB):
        """Verify `debug` reports OK for API, peers, and source prerequisites."""
        actual = peerdb.debug()
        expected = {
            "API": {
                "URL": HttpUrl("http://localhost:3000/api"),
                "Connection test": "OK",
            },
            "Source peer": {
                "URL": make_url("postgresql+psycopg2://postgres:postgres@localhost:25432/test"),
                "Connection test": "OK",
                "max_replication_slots >= 4": "OK",
                "max_wal_senders >= 1": "OK",
                "wal_level = logical": "OK",
            },
            "Destination peer": {
                "URL": make_url("clickhousedb+connect://default:default@localhost:28123/default"),
                "Connection test": "OK",
            },
        }
        assert actual == expected


class TestCreatePeer(PeerDBClickHouseTest):
    """Tests for `PeerDB.create_peer` creation and idempotency."""

    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB):
        """Verify creating a peer makes it discoverable."""
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        # Tear down
        peerdb.drop_peer(peer.name)

    def test_existant_peer_raises_exception_if_exists_fail(self, peerdb: PeerDB):
        """Verify recreating a peer with `if_exists=fail` raises."""
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        with pytest.raises(PeerExistsException) as exc:
            peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()}, if_exists="fail")

        assert str(exc.value) == "Peer 'source' exists"

        # Tear down
        peerdb.drop_peer(peer.name)

    def test_existant_peer_if_exists_keep(self, peerdb: PeerDB):
        """Verify recreating a peer with `if_exists=keep` keeps it."""
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
    """Tests for `PeerDB.drop_peer` removal and error handling."""

    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB):
        """Verify dropping a peer removes it."""
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        peerdb.create_peer({"name": peer.name, **peer.peerdb.model_dump()})
        assert peerdb.has_peer(peer.name) is True

        peerdb.drop_peer(peer.name)
        assert peerdb.has_peer(peer.name) is False

    def test_non_existant_peer_raises_exception(self, peerdb: PeerDB):
        """Verify dropping a missing peer raises."""
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == "source")

        with pytest.raises(PeerNotFoundException) as exc:
            peerdb.drop_peer(peer.name)

        assert str(exc.value) == "Peer 'source' not found"


class TestListPeers(PeerDBClickHouseTest):
    """Tests for `PeerDB.list_peers` enumeration."""

    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None):
        """Verify listing returns the configured source and destination peers."""
        actual = [peer.model_dump() for peer in peerdb.list_peers().items]
        expected = [
            {"name": "source", "type": "POSTGRES"},
            {"name": "destination", "type": "CLICKHOUSE"},
        ]
        assert_count_equal(actual, expected)


class TestCreateMirror(PeerDBClickHouseTest):
    """Tests for `PeerDB.create_mirror` creation and idempotency."""

    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers: None):
        """Verify creating a mirror makes it discoverable."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        # Tear down
        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)

    def test_non_existant_source_table_raises_exception(
        self, some_postgres_tables: list[Table], peerdb: PeerDB, peers: None
    ):
        """Verify creating a mirror with a missing source table raises."""
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
        """Verify recreating a mirror with `if_exists=fail` raises."""
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
        """Verify recreating a mirror with `if_exists=keep` keeps it."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_many")

        peerdb.create_mirror(mirror.model_dump())
        assert peerdb.has_mirror(mirror.flow_job_name) is True

        response = peerdb.create_mirror(mirror.model_dump(), if_exists="keep")
        assert response.message == "Kept mirror 'cdc_many'"

        # Tear down
        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)


class TestDropMirror(PeerDBClickHouseTest):
    """Tests for `PeerDB.drop_mirror` removal and destination handling."""

    def test_ok(
        self,
        all_postgres_tables: list[Table],
        peerdb: PeerDB,
        peers: None,
        destination_adapter: ClickHouseAdapter,
        mirror_with_destination_table: None,
    ):
        """Verify dropping a mirror removes it and its destination table."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")
        kwargs = table_kwargs(
            destination_adapter, mirror.table_mappings[0].destination_table_identifier
        )
        assert destination_adapter.has_table(**kwargs) is True

        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)
        assert peerdb.has_mirror(mirror.flow_job_name) is False
        assert destination_adapter.has_table(**kwargs) is False

    def test_keep_destination_tables(
        self,
        all_postgres_tables: list[Table],
        peerdb: PeerDB,
        peers: None,
        destination_adapter: ClickHouseAdapter,
        mirror_with_destination_table: None,
    ):
        """Verify dropping a mirror keeps the destination table when requested."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=False)
        assert peerdb.has_mirror(mirror.flow_job_name) is False

        kwargs = table_kwargs(
            destination_adapter, mirror.table_mappings[0].destination_table_identifier
        )
        assert destination_adapter.has_table(**kwargs) is True

        # Clean up
        destination_adapter.drop_table(if_exists=True, **kwargs)

    def test_create_mirror_not_in_config(
        self,
        all_postgres_tables: list[Table],
        peerdb: PeerDB,
        peers: None,
        extra_mirror: dict,
    ):
        """Verify an `extra_mirror` derived from `cdc_one` can be created."""
        peerdb.create_mirror(extra_mirror)
        assert peerdb.has_mirror("extra_mirror") is True

        # Tear down
        peerdb.drop_mirror("extra_mirror", drop_destination_tables=True)

    def test_drop_mirror_not_in_config(
        self,
        all_postgres_tables: list[Table],
        peerdb: PeerDB,
        peers: None,
        extra_mirror: dict,
    ):
        """Verify an `extra_mirror` derived from `cdc_one` can be dropped."""
        peerdb.create_mirror(extra_mirror)
        assert peerdb.has_mirror("extra_mirror") is True

        response = peerdb.drop_mirror("extra_mirror", drop_destination_tables=True)
        assert response.message == "Dropped mirror 'extra_mirror'"
        assert peerdb.has_mirror("extra_mirror") is False

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        """Verify dropping a missing mirror raises."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.drop_mirror(mirror.flow_job_name, drop_destination_tables=True)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestResyncMirror(PeerDBClickHouseTest):
    """Tests for `PeerDB.resync_mirror` initiation and error handling."""

    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None):
        """Verify resyncing a mirror initiates the resync."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        response = peerdb.resync_mirror(mirror.flow_job_name)

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        """Verify resyncing a missing mirror raises."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.resync_mirror(mirror.flow_job_name)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestPauseMirror(PeerDBClickHouseTest):
    """Tests for `PeerDB.pause_mirror` with mocked running status."""

    def test_ok(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None, monkeypatch
    ):
        """Verify pausing a running mirror reports success."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        # Mock the mirror status to STATUS_RUNNING so pause is allowed
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda flow_job_name: MirrorStatusResponse(
                createdAt=datetime.datetime.now(),  # noqa: DTZ005
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

        monkeypatch.setattr("dw_lib.peerdb.requests.post", lambda *a, **k: _Response())
        monkeypatch.setattr(peerdb, "wait_for_mirror_status", lambda *a, **k: "STATUS_PAUSED")

        response = peerdb.pause_mirror(mirror.flow_job_name)
        assert response.message == "Paused mirror 'cdc_one'"

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        """Verify pausing a missing mirror raises."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.pause_mirror(mirror.flow_job_name)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestResumeMirror(PeerDBClickHouseTest):
    """Tests for `PeerDB.resume_mirror` with mocked paused status."""

    def test_ok(
        self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None, monkeypatch
    ):
        """Verify resuming a paused mirror reports success."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        # Mock the mirror status to STATUS_PAUSED so resume is allowed
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda flow_job_name: MirrorStatusResponse(
                createdAt=datetime.datetime.now(),  # noqa: DTZ005
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

        monkeypatch.setattr("dw_lib.peerdb.requests.post", lambda *a, **k: _Response())
        monkeypatch.setattr(peerdb, "wait_for_mirror_status", lambda *a, **k: "STATUS_RUNNING")

        response = peerdb.resume_mirror(mirror.flow_job_name)
        assert response.message == "Resumed mirror 'cdc_one'"

    def test_non_existant_mirror_raises_exception(self, peerdb: PeerDB, peers: None):
        """Verify resuming a missing mirror raises."""
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

        with pytest.raises(MirrorNotFoundException) as exc:
            peerdb.resume_mirror(mirror.flow_job_name)

        assert str(exc.value) == "Mirror 'cdc_one' not found"


class TestListMirrors(PeerDBClickHouseTest):
    """Tests for `PeerDB.list_mirrors` enumeration."""

    def test_ok(self, all_postgres_tables: list[Table], peerdb: PeerDB, peers_and_mirrors: None):
        """Verify listing returns the configured ClickHouse mirrors."""
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
