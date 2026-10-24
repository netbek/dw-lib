from dw_lib.exceptions import MirrorFailedException, MirrorTimeoutException
from dw_lib.peerdb import MirrorStatusResponse, PeerDB
from pathlib import Path

import datetime
import pytest
import requests
import time


def make_peerdb(tmp_path: Path, operation_timeout: int = 2) -> PeerDB:
    """Return a PeerDB client with a minimal config."""
    config_file = tmp_path / "peerdb.yaml"
    config_file.write_text(
        f"peerdb_ui_url: http://localhost:3000\noperation_timeout: {operation_timeout}\n"
    )

    return PeerDB(config_file=config_file)


def use_statuses(monkeypatch, peerdb: PeerDB, statuses: list[str]) -> None:
    """Return the given mirror statuses in order and skip polling sleeps."""
    iterator = iter(statuses)

    def get_mirror_status(flow_job_name: str) -> MirrorStatusResponse:
        return MirrorStatusResponse(
            createdAt=datetime.datetime.now(),
            currentFlowState=next(iterator),
            flowJobName=flow_job_name,
        )

    monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)
    monkeypatch.setattr(time, "sleep", lambda _: None)


class FakeResponse:
    """Minimal HTTP response for resync requests."""

    def raise_for_status(self) -> None:
        pass


class TestPollMirrorStatus:
    """Tests for mirror status polling."""

    def test_returns_target_status(self, tmp_path: Path, monkeypatch):
        """Verify polling stops on the target status."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(monkeypatch, peerdb, ["STATUS_SNAPSHOT", "STATUS_RUNNING"])

        status = peerdb.wait_for_mirror_status("cdc_one", {"STATUS_RUNNING"}, timeout=2)

        assert status == "STATUS_RUNNING"

    def test_raises_on_fail_status(self, tmp_path: Path, monkeypatch):
        """Verify polling stops on a fail status."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(monkeypatch, peerdb, ["STATUS_SNAPSHOT", "STATUS_FAILED"])

        with pytest.raises(MirrorFailedException) as exc:
            peerdb.wait_for_mirror_status(
                "cdc_one",
                {"STATUS_RUNNING"},
                timeout=2,
                fail_statuses={"STATUS_FAILED"},
            )

        assert str(exc.value) == "Mirror 'cdc_one' reached status STATUS_FAILED"

    def test_raises_on_timeout(self, tmp_path: Path, monkeypatch):
        """Verify polling raises when the timeout expires."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(monkeypatch, peerdb, ["STATUS_SNAPSHOT", "STATUS_SNAPSHOT"])

        with pytest.raises(MirrorTimeoutException):
            peerdb.wait_for_mirror_status("cdc_one", {"STATUS_RUNNING"}, timeout=2)


class TestWaitForMirrorSnapshot:
    """Tests for waiting on initial and resync snapshots."""

    def test_create_waits_for_running(self, tmp_path: Path, monkeypatch):
        """Verify a normal mirror waits for STATUS_RUNNING."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(
            monkeypatch,
            peerdb,
            ["STATUS_SETUP", "STATUS_SNAPSHOT", "STATUS_RUNNING"],
        )

        assert peerdb.wait_for_mirror_snapshot("cdc_one") == "STATUS_RUNNING"

    def test_create_waits_for_completed(self, tmp_path: Path, monkeypatch):
        """Verify a snapshot-only mirror waits for STATUS_COMPLETED."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(
            monkeypatch,
            peerdb,
            ["STATUS_SETUP", "STATUS_SNAPSHOT", "STATUS_COMPLETED"],
        )

        assert peerdb.wait_for_mirror_snapshot("cdc_one") == "STATUS_COMPLETED"

    def test_resync_waits_for_start_and_completion(self, tmp_path: Path, monkeypatch):
        """Verify a running mirror waits through the resync phases."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(
            monkeypatch,
            peerdb,
            [
                "STATUS_RESYNC",
                "STATUS_SETUP",
                "STATUS_SNAPSHOT",
                "STATUS_RESYNC",
                "STATUS_RUNNING",
            ],
        )

        status = peerdb.wait_for_mirror_snapshot("cdc_one", initial_status="STATUS_RUNNING")

        assert status == "STATUS_RUNNING"

    def test_resync_from_snapshot_waits_for_completion(self, tmp_path: Path, monkeypatch):
        """Verify a mirror already snapshotting waits for the new resync to finish."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(
            monkeypatch,
            peerdb,
            ["STATUS_RESYNC", "STATUS_SETUP", "STATUS_SNAPSHOT", "STATUS_RUNNING"],
        )

        status = peerdb.wait_for_mirror_snapshot("cdc_one", initial_status="STATUS_SNAPSHOT")

        assert status == "STATUS_RUNNING"

    def test_fast_resync_fallback(self, tmp_path: Path, monkeypatch):
        """Verify a fast resync that returns to running is accepted."""
        peerdb = make_peerdb(tmp_path, operation_timeout=2)
        use_statuses(
            monkeypatch,
            peerdb,
            ["STATUS_RUNNING", "STATUS_RUNNING", "STATUS_RUNNING"],
        )

        status = peerdb.wait_for_mirror_snapshot("cdc_one", initial_status="STATUS_RUNNING")

        assert status == "STATUS_RUNNING"

    def test_raises_on_failure(self, tmp_path: Path, monkeypatch):
        """Verify a failed mirror stops the wait."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(monkeypatch, peerdb, ["STATUS_SETUP", "STATUS_FAILED"])

        with pytest.raises(MirrorFailedException):
            peerdb.wait_for_mirror_snapshot("cdc_one")

    def test_paused_is_not_complete(self, tmp_path: Path, monkeypatch):
        """Verify paused mirrors do not satisfy the wait."""
        peerdb = make_peerdb(tmp_path)
        use_statuses(
            monkeypatch,
            peerdb,
            ["STATUS_PAUSED", "STATUS_PAUSING", "STATUS_RUNNING"],
        )

        assert peerdb.wait_for_mirror_snapshot("cdc_one") == "STATUS_RUNNING"

    def test_completion_wait_has_no_timeout(self, tmp_path: Path, monkeypatch):
        """Verify the completion wait ignores the operation timeout."""
        peerdb = make_peerdb(tmp_path, operation_timeout=1)
        use_statuses(
            monkeypatch,
            peerdb,
            ["STATUS_SNAPSHOT"] * 5 + ["STATUS_RUNNING"],
        )

        assert peerdb.wait_for_mirror_snapshot("cdc_one") == "STATUS_RUNNING"


class TestResyncMirrorWait:
    """Tests for resync wait modes."""

    def test_wait_reports_completion(self, tmp_path: Path, monkeypatch):
        """Verify wait mode captures the initial status and reports completion."""
        peerdb = make_peerdb(tmp_path)
        calls = {}

        monkeypatch.setattr(peerdb, "has_mirror", lambda _: True)
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda flow_job_name: MirrorStatusResponse(
                createdAt=datetime.datetime.now(),
                currentFlowState="STATUS_RUNNING",
                flowJobName=flow_job_name,
            ),
        )
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())

        def wait_for_mirror_snapshot(flow_job_name: str, initial_status: str | None = None):
            calls["flow_job_name"] = flow_job_name
            calls["initial_status"] = initial_status

            return "STATUS_RUNNING"

        monkeypatch.setattr(peerdb, "wait_for_mirror_snapshot", wait_for_mirror_snapshot)

        response = peerdb.resync_mirror("cdc_one", wait=True)

        assert response.message == "Resynced mirror 'cdc_one'"
        assert calls == {"flow_job_name": "cdc_one", "initial_status": "STATUS_RUNNING"}

    def test_no_wait_reports_initiation(self, tmp_path: Path, monkeypatch):
        """Verify no-wait mode keeps the STATUS_RESYNC wait and message."""
        peerdb = make_peerdb(tmp_path)
        calls = {}

        monkeypatch.setattr(peerdb, "has_mirror", lambda _: True)
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())

        def wait_for_mirror_status(
            flow_job_name: str,
            target_statuses: set[str],
            timeout: int | None = None,
            fail_statuses: set[str] | None = None,
        ):
            calls["flow_job_name"] = flow_job_name
            calls["target_statuses"] = target_statuses
            calls["timeout"] = timeout

            return "STATUS_RESYNC"

        monkeypatch.setattr(peerdb, "wait_for_mirror_status", wait_for_mirror_status)

        response = peerdb.resync_mirror("cdc_one", wait=False, timeout=7)

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert calls == {
            "flow_job_name": "cdc_one",
            "target_statuses": {"STATUS_RESYNC"},
            "timeout": 7,
        }
