from dw_lib.exceptions import (
    GetDynamicSettingsException,
    MirrorNotFoundException,
    MirrorStatusException,
    MirrorTimeoutException,
)
from dw_lib.peerdb import (
    MirrorStatusResponse,
    PeerDB,
    RESYNC_STARTED_STATUSES,
    RESYNC_TERMINAL_STARTED_STATUSES,
)
from pathlib import Path

import datetime
import pytest
import requests


def make_peerdb(
    tmp_path: Path,
    timeout: int = 3,
    polling_interval: float = 1.0,
) -> PeerDB:
    """Write a minimal PeerDB config and return the client."""
    config_file = tmp_path / "peerdb.yaml"
    config_file.write_text(
        "client:\n"
        "  peerdb_ui_url: http://localhost:3000\n"
        f"  read_timeout: {timeout}\n"
        f"  polling_interval: {polling_interval}\n"
        f"  mirror_drop_polling_timeout: {timeout}\n"
        f"  mirror_pause_polling_timeout: {timeout}\n"
        f"  mirror_resume_polling_timeout: {timeout}\n"
        f"  mirror_resync_polling_timeout: {timeout}\n"
    )

    return PeerDB(config_file=config_file)


def mirror_status(flow_job_name: str, current_flow_state: str) -> MirrorStatusResponse:
    """Build a mirror status response."""
    return MirrorStatusResponse(
        createdAt=datetime.datetime.now(),
        currentFlowState=current_flow_state,
        flowJobName=flow_job_name,
    )


def fake_time(monkeypatch) -> list[float]:
    """Replace the polling clock; return a mutable list of sleep durations."""
    now = [0.0]
    sleeps: list[float] = []

    def monotonic() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr("dw_lib.peerdb.time.monotonic", monotonic)
    monkeypatch.setattr("dw_lib.peerdb.time.sleep", sleep)

    return sleeps


def status_sequence(monkeypatch, peerdb: PeerDB, states: list[str | None]) -> None:
    """Return statuses in order; None raises MirrorNotFoundException."""
    remaining = list(states)

    def fake_get_mirror_status(flow_job_name: str) -> MirrorStatusResponse:
        if not remaining:
            raise AssertionError("status sequence exhausted")

        state = remaining.pop(0)

        if state is None:
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        return mirror_status(flow_job_name, state)

    monkeypatch.setattr(peerdb, "get_mirror_status", fake_get_mirror_status)
    fake_time(monkeypatch)


class FakeResponse:
    """Minimal requests response for state-change calls."""

    def raise_for_status(self) -> None:
        return None


def fake_post(
    monkeypatch,
    calls: list[dict],
    timeouts: list[tuple[float, float]] | None = None,
) -> None:
    """Record state-change request bodies and timeouts."""

    def post(url, json=None, headers=None, timeout=None):
        calls.append(json)

        if timeouts is not None:
            timeouts.append(timeout)

        return FakeResponse()

    monkeypatch.setattr("dw_lib.peerdb.requests.post", post)


class FakeMirrorStatusResponse:
    """Minimal requests response for mirror status calls."""

    def __init__(self, data: dict, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def json(self) -> dict:
        return self._data


def fake_mirror_status_post(
    monkeypatch, calls: list[dict], data: dict, status_code: int = 200
) -> None:
    """Record mirror status request bodies and return a canned response."""

    def post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return FakeMirrorStatusResponse(data, status_code)

    monkeypatch.setattr("dw_lib.peerdb.requests.post", post)


def mirror_status_data(flow_job_name: str, cdc_status: dict | None = None) -> dict:
    """Build a mirror status API response."""
    data = {
        "createdAt": "2026-01-01T00:00:00Z",
        "currentFlowState": "STATUS_RUNNING",
        "flowJobName": flow_job_name,
    }

    if cdc_status is not None:
        data["cdcStatus"] = cdc_status

    return data


class TestGetMirrorStatus:
    """Tests for `PeerDB.get_mirror_status`."""

    def test_default_request_body(self, tmp_path: Path, monkeypatch):
        """Verify flow info is excluded by default."""
        peerdb = make_peerdb(tmp_path)
        calls: list[dict] = []
        fake_mirror_status_post(monkeypatch, calls, mirror_status_data("cdc_one"))

        response = peerdb.get_mirror_status("cdc_one")

        assert calls == [
            {
                "flowJobName": "cdc_one",
                "includeFlowInfo": False,
                "excludeBatches": False,
                "excludeSnapshotStatus": False,
            }
        ]
        assert response.cdc_status is None

    def test_include_flow_info_request_body(self, tmp_path: Path, monkeypatch):
        """Verify flow info is requested when enabled."""
        peerdb = make_peerdb(tmp_path)
        calls: list[dict] = []
        fake_mirror_status_post(
            monkeypatch,
            calls,
            mirror_status_data("cdc_one", cdc_status={"rowsSynced": "0"}),
        )

        response = peerdb.get_mirror_status("cdc_one", include_flow_info=True)

        assert calls == [
            {
                "flowJobName": "cdc_one",
                "includeFlowInfo": True,
                "excludeBatches": False,
                "excludeSnapshotStatus": False,
            }
        ]
        assert response.cdc_status is not None
        assert response.cdc_status.rows_synced == 0

    def test_exclude_batches_request_body(self, tmp_path: Path, monkeypatch):
        """Verify CDC batch history can be excluded."""
        peerdb = make_peerdb(tmp_path)
        calls: list[dict] = []
        fake_mirror_status_post(
            monkeypatch,
            calls,
            mirror_status_data("cdc_one", cdc_status={"rowsSynced": "0"}),
        )

        response = peerdb.get_mirror_status("cdc_one", include_flow_info=True, exclude_batches=True)

        assert calls == [
            {
                "flowJobName": "cdc_one",
                "includeFlowInfo": True,
                "excludeBatches": True,
                "excludeSnapshotStatus": False,
            }
        ]
        assert response.cdc_status is not None
        assert response.cdc_status.cdc_batches == []

    def test_exclude_snapshot_status_request_body(self, tmp_path: Path, monkeypatch):
        """Verify initial-load snapshot status can be excluded."""
        peerdb = make_peerdb(tmp_path)
        calls: list[dict] = []
        fake_mirror_status_post(
            monkeypatch,
            calls,
            mirror_status_data("cdc_one", cdc_status={"rowsSynced": "0"}),
        )

        peerdb.get_mirror_status("cdc_one", include_flow_info=True, exclude_snapshot_status=True)

        assert calls == [
            {
                "flowJobName": "cdc_one",
                "includeFlowInfo": True,
                "excludeBatches": False,
                "excludeSnapshotStatus": True,
            }
        ]

    def test_exclude_batches_and_snapshot_status_request_body(self, tmp_path: Path, monkeypatch):
        """Verify both exclude flags can be combined."""
        peerdb = make_peerdb(tmp_path)
        calls: list[dict] = []
        fake_mirror_status_post(
            monkeypatch,
            calls,
            mirror_status_data("cdc_one", cdc_status={"rowsSynced": "0"}),
        )

        peerdb.get_mirror_status(
            "cdc_one",
            include_flow_info=True,
            exclude_batches=True,
            exclude_snapshot_status=True,
        )

        assert calls == [
            {
                "flowJobName": "cdc_one",
                "includeFlowInfo": True,
                "excludeBatches": True,
                "excludeSnapshotStatus": True,
            }
        ]

    def test_parses_cdc_status(self, tmp_path: Path, monkeypatch):
        """Verify CDC status details are parsed from the response."""
        peerdb = make_peerdb(tmp_path)
        calls: list[dict] = []
        cdc_status = {
            "config": {
                "flowJobName": "cdc_one",
                "tableMappings": [
                    {
                        "sourceTableIdentifier": "public.sales",
                        "destinationTableIdentifier": "public_sales",
                        "partitionKey": "",
                        "exclude": [],
                    }
                ],
                "maxBatchSize": 1000000,
                "idleTimeoutSeconds": "60",
                "doInitialSnapshot": True,
                "snapshotNumRowsPerPartition": 1000000,
                "snapshotMaxParallelWorkers": 4,
                "snapshotNumTablesInParallel": 1,
                "resync": False,
                "initialSnapshotOnly": False,
                "softDeleteColName": "_PEERDB_IS_DELETED",
                "syncedAtColName": "_PEERDB_SYNCED_AT",
                "script": "",
                "system": "Q",
                "sourceName": "postgres_local",
                "destinationName": "bq_peer",
            },
            "snapshotStatus": {
                "clones": [
                    {
                        "tableName": "public_sales",
                        "startTime": "2024-06-27T14:37:48.701204Z",
                        "numPartitionsCompleted": 1,
                        "numPartitionsTotal": 1,
                        "numRowsSynced": "4",
                        "avgTimePerPartitionMs": "11381",
                        "flowJobName": "clone_cdc_one_public_sales",
                        "sourceTable": "public.sales",
                        "fetchCompleted": True,
                        "consolidateCompleted": True,
                        "mirrorName": "cdc_one",
                    }
                ]
            },
            "cdcBatches": [
                {
                    "startLsn": "123",
                    "endLsn": "456",
                    "numRows": "10",
                    "startTime": "2024-06-27T14:37:48Z",
                    "endTime": "2024-06-27T14:38:48Z",
                    "batchId": "1",
                }
            ],
            "sourceType": "POSTGRES",
            "destinationType": "BIGQUERY",
            "rowsSynced": "14",
        }
        fake_mirror_status_post(
            monkeypatch, calls, mirror_status_data("cdc_one", cdc_status=cdc_status)
        )

        response = peerdb.get_mirror_status("cdc_one", include_flow_info=True)

        assert response.cdc_status is not None
        assert response.cdc_status.config is not None
        assert response.cdc_status.config.flow_job_name == "cdc_one"
        assert response.cdc_status.config.idle_timeout_seconds == 60
        assert (
            response.cdc_status.config.table_mappings[0].source_table_identifier == "public.sales"
        )
        assert response.cdc_status.snapshot_status is not None
        assert response.cdc_status.snapshot_status.clones[0].num_rows_synced == 4
        assert response.cdc_status.cdc_batches[0].batch_id == 1
        assert response.cdc_status.source_type == "POSTGRES"
        assert response.cdc_status.destination_type == "BIGQUERY"
        assert response.cdc_status.rows_synced == 14


class TestWaitForMirrorStatus:
    """Tests for `PeerDB.wait_for_mirror_status`."""

    def test_returns_target_status(self, tmp_path: Path, monkeypatch):
        """Verify polling stops on a target status."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_PAUSED"])

        assert peerdb.wait_for_mirror_status("cdc_one", {"STATUS_PAUSED"}) == "STATUS_PAUSED"

    @pytest.mark.parametrize(
        "state",
        [
            "STATUS_COMPLETED",
            "STATUS_FAILED",
            "STATUS_TERMINATING",
            "STATUS_TERMINATED",
        ],
    )
    def test_raises_on_stopped_status(self, tmp_path: Path, monkeypatch, state: str):
        """Verify stopped statuses raise instead of waiting for a timeout."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, [state])

        with pytest.raises(MirrorStatusException):
            peerdb.wait_for_mirror_status("cdc_one", {"STATUS_RUNNING"})

    def test_raises_on_timeout(self, tmp_path: Path, monkeypatch):
        """Verify an unreached target raises a timeout."""
        peerdb = make_peerdb(tmp_path, timeout=2)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", "STATUS_RUNNING"])

        with pytest.raises(MirrorTimeoutException):
            peerdb.wait_for_mirror_status("cdc_one", {"STATUS_PAUSED"})

    def test_uses_polling_interval(self, tmp_path: Path, monkeypatch):
        """Verify polling sleeps for the configured interval."""
        peerdb = make_peerdb(tmp_path, polling_interval=2.5)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", "STATUS_PAUSED"])
        sleeps = fake_time(monkeypatch)

        peerdb.wait_for_mirror_status("cdc_one", {"STATUS_PAUSED"})

        assert sleeps == [2.5]


class TestResumeMirror:
    """Tests for `PeerDB.resume_mirror`."""

    def test_pausing_waits_for_paused_then_resumes(self, tmp_path: Path, monkeypatch):
        """Verify a pausing mirror is resumed after it reaches paused."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_PAUSING", "STATUS_PAUSED", "STATUS_RUNNING"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        response = peerdb.resume_mirror("cdc_one")

        assert response.message == "Resumed mirror 'cdc_one'"
        assert calls == [{"flowJobName": "cdc_one", "requestedFlowState": "STATUS_RUNNING"}]

    def test_paused_resumes(self, tmp_path: Path, monkeypatch):
        """Verify a paused mirror is resumed directly."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_PAUSED", "STATUS_RUNNING"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        response = peerdb.resume_mirror("cdc_one")

        assert response.message == "Resumed mirror 'cdc_one'"
        assert len(calls) == 1

    def test_terminated_raises(self, tmp_path: Path, monkeypatch):
        """Verify a terminated mirror cannot be resumed."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_TERMINATED"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        with pytest.raises(MirrorStatusException):
            peerdb.resume_mirror("cdc_one")

        assert calls == []


class TestResyncMirror:
    """Tests for `PeerDB.resync_mirror`."""

    def test_running_waits_for_resync_start(self, tmp_path: Path, monkeypatch):
        """Verify a running mirror waits for a resync-started status."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)
        targets: list[set[str]] = []

        def fake_wait(flow_job_name: str, target_statuses: set[str], timeout=None) -> str:
            targets.append(target_statuses)
            return "STATUS_SETUP"

        monkeypatch.setattr(peerdb, "wait_for_mirror_status", fake_wait)

        response = peerdb.resync_mirror("cdc_one")

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert targets == [RESYNC_STARTED_STATUSES]
        assert len(calls) == 1

    @pytest.mark.parametrize("state", ["STATUS_COMPLETED", "STATUS_FAILED"])
    def test_terminal_accepts_new_flow_statuses(self, tmp_path: Path, monkeypatch, state: str):
        """Verify a terminal mirror accepts the recreated flow statuses."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, [state])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)
        targets: list[set[str]] = []

        def fake_wait(flow_job_name: str, target_statuses: set[str], timeout=None) -> str:
            targets.append(target_statuses)
            return "STATUS_SETUP"

        monkeypatch.setattr(peerdb, "wait_for_mirror_status", fake_wait)

        response = peerdb.resync_mirror("cdc_one")

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert targets == [RESYNC_TERMINAL_STARTED_STATUSES]
        assert len(calls) == 1

    @pytest.mark.parametrize("state", ["STATUS_TERMINATING", "STATUS_TERMINATED"])
    def test_terminating_or_terminated_raises(self, tmp_path: Path, monkeypatch, state: str):
        """Verify terminating and terminated mirrors cannot be resynced."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, [state])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        with pytest.raises(MirrorStatusException):
            peerdb.resync_mirror("cdc_one")

        assert calls == []


class TestDropMirror:
    """Tests for `PeerDB.drop_mirror`."""

    def test_terminated_raises(self, tmp_path: Path, monkeypatch):
        """Verify a terminated mirror cannot be dropped."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_TERMINATED"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        with pytest.raises(MirrorStatusException):
            peerdb.drop_mirror("cdc_one")

        assert calls == []

    def test_waits_until_mirror_disappears(self, tmp_path: Path, monkeypatch):
        """Verify a running mirror is polled until it disappears."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", None])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        response = peerdb.drop_mirror("cdc_one")

        assert response.message == "Dropped mirror 'cdc_one'"
        assert len(calls) == 1

    def test_uses_configured_request_timeout(self, tmp_path: Path, monkeypatch):
        """Verify drop requests use the configured connect and request timeouts."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", None])
        calls: list[dict] = []
        timeouts: list[tuple[float, float]] = []
        fake_post(monkeypatch, calls, timeouts)

        peerdb.drop_mirror("cdc_one")

        assert timeouts == [(5, 900)]

    def test_status_becoming_terminated_raises(self, tmp_path: Path, monkeypatch):
        """Verify a mirror that becomes terminated while dropping raises."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", "STATUS_TERMINATED"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        with pytest.raises(MirrorStatusException):
            peerdb.drop_mirror("cdc_one")

        assert len(calls) == 1


class TestPauseMirror:
    """Tests for `PeerDB.pause_mirror`."""

    def test_terminated_raises(self, tmp_path: Path, monkeypatch):
        """Verify a terminated mirror cannot be paused."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_TERMINATED"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        with pytest.raises(MirrorStatusException):
            peerdb.pause_mirror("cdc_one")

        assert calls == []

    def test_running_pauses(self, tmp_path: Path, monkeypatch):
        """Verify a running mirror is paused."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", "STATUS_PAUSED"])
        calls: list[dict] = []
        fake_post(monkeypatch, calls)

        response = peerdb.pause_mirror("cdc_one")

        assert response.message == "Paused mirror 'cdc_one'"
        assert calls == [{"flowJobName": "cdc_one", "requestedFlowState": "STATUS_PAUSED"}]

    def test_uses_configured_request_timeout(self, tmp_path: Path, monkeypatch):
        """Verify pause requests use the configured connect and request timeouts."""
        peerdb = make_peerdb(tmp_path)
        status_sequence(monkeypatch, peerdb, ["STATUS_RUNNING", "STATUS_PAUSED"])
        calls: list[dict] = []
        timeouts: list[tuple[float, float]] = []
        fake_post(monkeypatch, calls, timeouts)

        peerdb.pause_mirror("cdc_one")

        assert timeouts == [(5, 60)]


class TestRequestTimeouts:
    """Tests for request timeout handling."""

    def test_can_connect_returns_false_on_timeout(self, tmp_path: Path, monkeypatch):
        """Verify a timeout during the connectivity check returns False."""
        peerdb = make_peerdb(tmp_path)

        def get(*args, **kwargs):
            raise requests.Timeout("timed out")

        monkeypatch.setattr("dw_lib.peerdb.requests.get", get)

        assert peerdb.can_connect() is False

    def test_get_settings_raises_on_timeout(self, tmp_path: Path, monkeypatch):
        """Verify a timeout while reading settings raises a client exception."""
        peerdb = make_peerdb(tmp_path)

        def get(*args, **kwargs):
            raise requests.Timeout("timed out")

        monkeypatch.setattr("dw_lib.peerdb.requests.get", get)

        with pytest.raises(GetDynamicSettingsException):
            peerdb.get_settings()
