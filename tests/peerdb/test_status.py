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
    operation_interval: float = 1.0,
) -> PeerDB:
    """Write a minimal PeerDB config and return the client."""
    config_file = tmp_path / "peerdb.yaml"
    config_file.write_text(
        "client:\n"
        "  peerdb_ui_url: http://localhost:3000\n"
        f"  read_timeout: {timeout}\n"
        f"  operation_interval: {operation_interval}\n"
        f"  mirror_drop_operation_timeout: {timeout}\n"
        f"  mirror_pause_operation_timeout: {timeout}\n"
        f"  mirror_resume_operation_timeout: {timeout}\n"
        f"  mirror_resync_operation_timeout: {timeout}\n"
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

    def test_uses_operation_interval(self, tmp_path: Path, monkeypatch):
        """Verify polling sleeps for the configured interval."""
        peerdb = make_peerdb(tmp_path, operation_interval=2.5)
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
