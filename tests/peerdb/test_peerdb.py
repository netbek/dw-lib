from ..conftest import PeerDBTest
from collections.abc import Generator, Iterator
from dw_lib.database import PostgresAdapter
from dw_lib.peerdb import PeerDB
from dw_lib.types import HttpUrl, PostgresSettings
from pathlib import Path
from pytest_docker.plugin import get_docker_services, Services
from ruamel.yaml import YAML
from typing import Any

import docker
import pydash
import pytest
import requests


class TestIntegration(PeerDBTest):
    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        return Path(__file__).parent / "data" / "peerdb.postgres.yaml"

    def test_can_connect(self, peerdb: PeerDB):
        assert peerdb.can_connect() is True

    def test_get_and_update_settings(self, peerdb: PeerDB):
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value is None

        peerdb.update_settings({"PEERDB_NULLABLE": "false"})
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "false"

        peerdb.update_settings({"PEERDB_NULLABLE": "true"})
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "true"


@pytest.mark.docker_skip_wait_until_responsive
class TestServicesOffline(PeerDBTest):
    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        return Path(__file__).parent / "data" / "peerdb.offline.yaml"

    def test_can_connect(self, peerdb: PeerDB):
        assert peerdb.can_connect() is False

    def test_get_and_update_settings(self, peerdb: PeerDB):
        with pytest.raises(Exception, match=r".*Failed to get dynamic settings.*"):
            peerdb.get_settings().settings

        with pytest.raises(Exception, match=r".*Failed to set.*"):
            peerdb.update_settings({"PEERDB_NULLABLE": "false"})


class TestReplicationSlots:
    @pytest.fixture(scope="function")
    def docker_compose_file(self, request) -> Path:
        marker = request.node.get_closest_marker("docker_compose_file")
        return Path(__file__).parent.parent / marker.args[0]

    @pytest.fixture(scope="function")
    def docker_compose_project_name(self) -> str:
        return "dw-lib-test-peerdb-replication-slots"  # Pin the project name to avoid creating multiple stacks

    # @pytest.fixture(scope="function")
    # def docker_setup(self) -> list[str] | str:
    #     return ["down -v", "up --build -d"]  # Stop the stack before starting a new one

    @pytest.fixture(scope="function")
    def docker_api(self) -> docker.client.DockerClient:
        return docker.from_env()

    @pytest.fixture(scope="function")
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

    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        return Path(__file__).parent / "data" / "peerdb.postgres.yaml"

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

    @pytest.fixture(scope="function")
    def postgres_primary_adapter(self, docker_services) -> Generator[PostgresAdapter, Any, None]:
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
    def postgres_replica_adapter(self, docker_services) -> Generator[PostgresAdapter, Any, None]:
        postgres_settings = PostgresSettings(
            host="localhost",
            port=25433,
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

    @pytest.mark.docker_compose_file("docker-compose.peerdb.wal_status_reserved.yml")
    def test_wal_status_reserved(
        self,
        postgres_primary_adapter: PostgresAdapter,
        postgres_replica_adapter: PostgresAdapter,
        peerdb: PeerDB,
    ):
        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute("create publication test_publication for table test_table;")

        with postgres_replica_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute(
                "create subscription test_subscription connection 'host=postgres-primary port=5432 user=postgres password=postgres dbname=test' publication test_publication;"
            )

        replication_slot = pydash.find(
            peerdb.list_replication_slots(), lambda x: x.slot_name == "test_subscription"
        )
        assert replication_slot is not None
        assert pydash.omit(
            replication_slot.model_dump(),
            [
                "confirmed_flush_lsn",
                "confirmed_to_current_mb",
                "current_lsn",
                "inactive_since",
                "lag_mb",
                "redo_lsn",
                "restart_lsn",
                "restart_to_confirmed_mb",
                "safe_wal_size",
                "sent_lsn",
                "wait_event_type",
                "wait_event",
            ],
        ) == {
            "active": True,
            "backend_state": "active",
            "failover": False,
            "logical_decoding_work_mem_mb": 64,
            "slot_name": "test_subscription",
            "spill_bytes": 0,
            "spill_count": 0,
            "spill_txns": 0,
            "stats_reset": None,
            "synced": False,
            "wal_status": "reserved",
        }
        assert replication_slot.confirmed_flush_lsn is not None
        assert replication_slot.confirmed_to_current_mb == 0
        assert replication_slot.current_lsn is not None
        assert replication_slot.inactive_since is None
        assert replication_slot.lag_mb == 0
        assert replication_slot.redo_lsn is not None
        assert replication_slot.restart_lsn is not None
        assert replication_slot.restart_to_confirmed_mb == 0
        assert replication_slot.safe_wal_size is not None
        assert replication_slot.sent_lsn is not None

    @pytest.mark.docker_compose_file("docker-compose.peerdb.wal_status_extended.yml")
    def test_wal_status_extended(
        self,
        docker_api: docker.client.DockerClient,
        postgres_primary_adapter: PostgresAdapter,
        postgres_replica_adapter: PostgresAdapter,
        peerdb: PeerDB,
    ):
        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute("create publication test_publication for table test_table;")

        with postgres_replica_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute(
                "create subscription test_subscription connection 'host=postgres-primary port=5432 user=postgres password=postgres dbname=test' publication test_publication;"
            )

        # Ensure the replica is running, then stop it to accumulate WAL
        postgres_replica_container = docker_api.containers.list(
            filters={"name": "postgres-replica"}
        ).pop()
        assert postgres_replica_container.status == "running"
        postgres_replica_container.stop(timeout=0)
        postgres_replica_container.reload()
        assert postgres_replica_container.status == "exited"

        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            # Generate ~80MB of data (between 64MB max_wal_size and 128MB max_slot_wal_keep_size)
            cur.execute(
                "insert into test_table (data) select repeat('a', 1000) from generate_series(1, 80000);"
            )
            # Force checkpoint so that wal_status updates immediately
            cur.execute("checkpoint;")

        replication_slot = pydash.find(
            peerdb.list_replication_slots(), lambda x: x.slot_name == "test_subscription"
        )
        assert replication_slot is not None
        assert pydash.omit(
            replication_slot.model_dump(),
            [
                "confirmed_flush_lsn",
                "confirmed_to_current_mb",
                "current_lsn",
                "inactive_since",
                "lag_mb",
                "redo_lsn",
                "restart_lsn",
                "restart_to_confirmed_mb",
                "safe_wal_size",
                "sent_lsn",
                "wait_event_type",
                "wait_event",
            ],
        ) == {
            "active": False,
            "backend_state": None,
            "failover": False,
            "logical_decoding_work_mem_mb": 64,
            "slot_name": "test_subscription",
            "spill_bytes": 0,
            "spill_count": 0,
            "spill_txns": 0,
            "stats_reset": None,
            "synced": False,
            "wal_status": "extended",
        }
        assert replication_slot.confirmed_flush_lsn is not None
        assert replication_slot.confirmed_to_current_mb is not None
        assert replication_slot.current_lsn is not None
        assert replication_slot.inactive_since is not None
        assert replication_slot.lag_mb is not None
        assert replication_slot.redo_lsn is not None
        assert replication_slot.restart_lsn is not None
        assert replication_slot.restart_to_confirmed_mb == 0
        assert replication_slot.safe_wal_size is not None
        assert replication_slot.sent_lsn is None

    @pytest.mark.docker_compose_file("docker-compose.peerdb.wal_status_reserved.yml")
    def test_wal_status_unreserved(
        self,
        docker_api: docker.client.DockerClient,
        postgres_primary_adapter: PostgresAdapter,
        postgres_replica_adapter: PostgresAdapter,
        peerdb: PeerDB,
    ):
        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute("create publication test_publication for table test_table;")

        with postgres_replica_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute(
                "create subscription test_subscription connection 'host=postgres-primary port=5432 user=postgres password=postgres dbname=test' publication test_publication;"
            )

        # Ensure the replica is running, then stop it to accumulate WAL
        postgres_replica_container = docker_api.containers.list(
            filters={"name": "postgres-replica"}
        ).pop()
        assert postgres_replica_container.status == "running"
        postgres_replica_container.stop(timeout=0)
        postgres_replica_container.reload()
        assert postgres_replica_container.status == "exited"

        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            # Generate ~45MB of data (between 32MB max_slot_wal_keep_size and 64MB max_wal_size)
            cur.execute(
                "insert into test_table (data) select repeat('a', 1000) from generate_series(1, 45000);"
            )

        replication_slot = pydash.find(
            peerdb.list_replication_slots(), lambda x: x.slot_name == "test_subscription"
        )
        assert replication_slot is not None
        assert pydash.omit(
            replication_slot.model_dump(),
            [
                "confirmed_flush_lsn",
                "confirmed_to_current_mb",
                "current_lsn",
                "inactive_since",
                "lag_mb",
                "redo_lsn",
                "restart_lsn",
                "restart_to_confirmed_mb",
                "safe_wal_size",
                "sent_lsn",
                "wait_event_type",
                "wait_event",
            ],
        ) == {
            "active": False,
            "backend_state": None,
            "failover": False,
            "logical_decoding_work_mem_mb": 64,
            "slot_name": "test_subscription",
            "spill_bytes": 0,
            "spill_count": 0,
            "spill_txns": 0,
            "stats_reset": None,
            "synced": False,
            "wal_status": "unreserved",
        }
        assert replication_slot.confirmed_flush_lsn is not None
        assert replication_slot.confirmed_to_current_mb is not None
        assert replication_slot.current_lsn is not None
        assert replication_slot.inactive_since is not None
        assert replication_slot.lag_mb is not None
        assert replication_slot.redo_lsn is not None
        assert replication_slot.restart_lsn is not None
        assert replication_slot.restart_to_confirmed_mb == 0
        assert replication_slot.safe_wal_size is not None
        assert replication_slot.sent_lsn is None

    @pytest.mark.docker_compose_file("docker-compose.peerdb.wal_status_reserved.yml")
    def test_wal_status_lost(
        self,
        docker_api: docker.client.DockerClient,
        postgres_primary_adapter: PostgresAdapter,
        postgres_replica_adapter: PostgresAdapter,
        peerdb: PeerDB,
    ):
        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute("create publication test_publication for table test_table;")

        with postgres_replica_adapter.create_client(autocommit=True) as (conn, cur):
            cur.execute("create table test_table (id serial primary key, data text);")
            cur.execute(
                "create subscription test_subscription connection 'host=postgres-primary port=5432 user=postgres password=postgres dbname=test' publication test_publication;"
            )

        # Ensure the replica is running, then stop it to accumulate WAL
        postgres_replica_container = docker_api.containers.list(
            filters={"name": "postgres-replica"}
        ).pop()
        assert postgres_replica_container.status == "running"
        postgres_replica_container.stop(timeout=0)
        postgres_replica_container.reload()
        assert postgres_replica_container.status == "exited"

        with postgres_primary_adapter.create_client(autocommit=True) as (conn, cur):
            # Generate ~80MB of data
            cur.execute(
                "insert into test_table (data) select repeat('a', 1000) from generate_series(1, 80000);"
            )
            # Force checkpoint so that wal_status updates immediately
            cur.execute("checkpoint;")

        replication_slot = pydash.find(
            peerdb.list_replication_slots(), lambda x: x.slot_name == "test_subscription"
        )
        assert replication_slot is not None
        assert pydash.omit(
            replication_slot.model_dump(),
            [
                "confirmed_flush_lsn",
                "confirmed_to_current_mb",
                "current_lsn",
                "inactive_since",
                "lag_mb",
                "redo_lsn",
                "restart_lsn",
                "restart_to_confirmed_mb",
                "safe_wal_size",
                "sent_lsn",
                "wait_event_type",
                "wait_event",
            ],
        ) == {
            "active": False,
            "backend_state": None,
            "failover": False,
            "logical_decoding_work_mem_mb": 64,
            "slot_name": "test_subscription",
            "spill_bytes": 0,
            "spill_count": 0,
            "spill_txns": 0,
            "stats_reset": None,
            "synced": False,
            "wal_status": "lost",
        }
        assert replication_slot.confirmed_flush_lsn is not None
        assert replication_slot.confirmed_to_current_mb is not None
        assert replication_slot.current_lsn is not None
        assert replication_slot.inactive_since is not None
        assert replication_slot.lag_mb is None
        assert replication_slot.redo_lsn is not None
        assert replication_slot.restart_lsn is None
        assert replication_slot.restart_to_confirmed_mb is None
        assert replication_slot.safe_wal_size is None
        assert replication_slot.sent_lsn is None
