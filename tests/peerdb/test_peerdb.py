from ..conftest import PeerDBTest
from dw_lib.exceptions import (
    GetDynamicSettingsException,
    GetMirrorStatusException,
    MirrorFailedException,
    MirrorNotFoundException,
    MirrorTimeoutException,
    ResyncMirrorException,
    SetDynamicSettingsException,
)
from dw_lib.peerdb import MirrorStatusResponse, PeerDB, RESYNC_START_TIMEOUT
from pathlib import Path

import datetime
import pydash
import pytest
import requests


class FakeClock:
    """Advance time only when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(scope="function")
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Provide a fake clock for bounded waits."""
    fake_clock = FakeClock()
    monkeypatch.setattr("dw_lib.peerdb.time.monotonic", fake_clock.monotonic)
    monkeypatch.setattr("dw_lib.peerdb.time.sleep", fake_clock.sleep)
    return fake_clock


class TestIntegration(PeerDBTest):
    """Integration tests for `PeerDB` connectivity and settings."""

    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        """Provide the Postgres PeerDB config path."""
        return Path(__file__).parent / "fixtures" / "peerdb.postgres.yaml"

    def test_can_connect(self, peerdb: PeerDB):
        """Verify the client connects to a running instance."""
        assert peerdb.can_connect() is True

    def test_get_and_update_settings(self, peerdb: PeerDB):
        """Verify dynamic settings round-trip through get and update."""
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
    """Offline tests for connection failures and settings errors."""

    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        """Provide the offline PeerDB config path."""
        return Path(__file__).parent / "fixtures" / "peerdb.offline.yaml"

    def test_can_connect(self, peerdb: PeerDB):
        """Verify the client reports no connection when services are offline."""
        assert peerdb.can_connect() is False

    def test_get_and_update_settings(self, peerdb: PeerDB):
        """Verify settings access raises when services are offline."""
        with pytest.raises(GetDynamicSettingsException):
            print(peerdb.get_settings().settings)

        with pytest.raises(SetDynamicSettingsException):
            peerdb.update_settings({"PEERDB_NULLABLE": "false"})


class TestWaitForMirrorReady:
    """Offline tests for mirror readiness polling."""

    @pytest.fixture(scope="function")
    def peerdb(self) -> PeerDB:
        """Provide a client that does not contact the server."""
        return PeerDB(Path(__file__).parent / "fixtures" / "peerdb.offline.yaml")

    @staticmethod
    def _status(flow_state: str) -> MirrorStatusResponse:
        return MirrorStatusResponse(
            createdAt=datetime.datetime.now(datetime.UTC),
            currentFlowState=flow_state,
            flowJobName="cdc_one",
        )

    def test_waits_until_running(self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify the wait returns when a CDC mirror reaches running."""
        states = iter(["STATUS_SETUP", "STATUS_SNAPSHOT", "STATUS_RUNNING"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", lambda _: None)

        assert peerdb.wait_for_mirror_ready("cdc_one") == "STATUS_RUNNING"

    def test_waits_until_completed(self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify the wait returns when a snapshot-only mirror completes."""
        states = iter(["STATUS_SETUP", "STATUS_SNAPSHOT", "STATUS_COMPLETED"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", lambda _: None)

        assert peerdb.wait_for_mirror_ready("cdc_one") == "STATUS_COMPLETED"

    def test_has_no_timeout(self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify a long sequence of snapshot states does not time out."""
        states = iter(["STATUS_SNAPSHOT"] * 20 + ["STATUS_RUNNING"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", lambda _: None)

        assert peerdb.wait_for_mirror_ready("cdc_one") == "STATUS_RUNNING"

    @pytest.mark.parametrize(
        "flow_state",
        ["STATUS_FAILED", "STATUS_TERMINATED", "STATUS_TERMINATING"],
    )
    def test_raises_on_failure(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, flow_state: str
    ) -> None:
        """Verify failure states raise instead of polling forever."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(flow_state))

        with pytest.raises(MirrorFailedException):
            peerdb.wait_for_mirror_ready("cdc_one")

    def test_raises_when_mirror_disappears(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a missing mirror raises instead of polling forever."""

        def get_mirror_status(_: str) -> MirrorStatusResponse:
            raise MirrorNotFoundException("Mirror 'cdc_one' not found")

        monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)

        with pytest.raises(MirrorFailedException):
            peerdb.wait_for_mirror_ready("cdc_one")

    def test_retries_transient_status_error(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify transient status errors are retried."""
        calls = []

        def get_mirror_status(_: str) -> MirrorStatusResponse:
            calls.append(1)
            if len(calls) < 3:
                raise GetMirrorStatusException("temporary")
            return self._status("STATUS_RUNNING")

        monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)

        assert peerdb.wait_for_mirror_ready("cdc_one") == "STATUS_RUNNING"
        assert len(calls) == 3

    def test_raises_after_sustained_status_errors(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify sustained status errors abort the wait."""
        monkeypatch.setattr("dw_lib.peerdb.STATUS_ERROR_WINDOW", 5)

        def get_mirror_status(_: str) -> MirrorStatusResponse:
            raise GetMirrorStatusException("temporary")

        monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)

        with pytest.raises(GetMirrorStatusException):
            peerdb.wait_for_mirror_ready("cdc_one")

    def test_read_timeout_is_wrapped(self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify read timeouts are wrapped in GetMirrorStatusException."""

        def post(*args, **kwargs):
            raise requests.ReadTimeout("timed out")

        monkeypatch.setattr("dw_lib.peerdb.requests.post", post)

        with pytest.raises(GetMirrorStatusException):
            peerdb.get_mirror_status("cdc_one")

    def test_unknown_status_raises_after_grace(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify an unknown status raises after the grace period."""
        monkeypatch.setattr("dw_lib.peerdb.STATUS_UNKNOWN_GRACE", 5)
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_UNKNOWN"))

        with pytest.raises(MirrorFailedException):
            peerdb.wait_for_mirror_ready("cdc_one")

    def test_reports_status_changes_and_heartbeats(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify the callback reports changes and periodic heartbeats."""
        monkeypatch.setattr("dw_lib.peerdb.STATUS_HEARTBEAT_INTERVAL", 5)
        states = iter(["STATUS_SNAPSHOT"] * 10 + ["STATUS_RUNNING"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))
        seen = []

        peerdb.wait_for_mirror_ready(
            "cdc_one", on_status_change=lambda status, _: seen.append(status)
        )

        assert seen[0] == "STATUS_SNAPSHOT"
        assert seen[-1] == "STATUS_RUNNING"
        assert seen.count("STATUS_SNAPSHOT") >= 2

    def test_wait_for_mirror_status_without_timeout(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a status wait with no timeout returns when its target appears."""
        states = iter(["STATUS_SNAPSHOT"] * 20 + ["STATUS_RESYNC"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", lambda _: None)

        assert (
            peerdb.wait_for_mirror_status("cdc_one", {"STATUS_RESYNC"}, timeout=None)
            == "STATUS_RESYNC"
        )


class TestWaitForMirrorResyncStarted:
    """Offline tests for the bounded resync-start wait."""

    @pytest.fixture(scope="function")
    def peerdb(self) -> PeerDB:
        """Provide a client that does not contact the server."""
        return PeerDB(Path(__file__).parent / "fixtures" / "peerdb.offline.yaml")

    @staticmethod
    def _status(flow_state: str) -> MirrorStatusResponse:
        return MirrorStatusResponse(
            createdAt=datetime.datetime.now(datetime.UTC),
            currentFlowState=flow_state,
            flowJobName="cdc_one",
        )

    def test_accepts_setup_for_running_mirror(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify a recreated flow in setup counts as a started resync."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_SETUP"))

        assert (
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)
            == "STATUS_SETUP"
        )

    def test_accepts_resync_then_snapshot(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify the wait follows the drop phase to the recreated flow."""
        states = iter(["STATUS_RESYNC", "STATUS_SNAPSHOT"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))

        assert (
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)
            == "STATUS_SNAPSHOT"
        )

    def test_accepts_running_after_resync(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify a fast resync may finish before the recreated flow is observed."""
        states = iter(["STATUS_RESYNC", "STATUS_RUNNING"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))

        assert (
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)
            == "STATUS_RUNNING"
        )

    def test_times_out_when_still_running(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify the wait is bounded when the resync is never observed."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_RUNNING"))

        with pytest.raises(MirrorTimeoutException):
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)

    def test_times_out_when_resync_stuck(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify a failed drop that leaves the mirror in resync times out."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_RESYNC"))

        with pytest.raises(MirrorTimeoutException):
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)

    def test_raises_on_failure(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify a failure state stops the wait immediately."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_FAILED"))

        with pytest.raises(MirrorFailedException):
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)

    def test_raises_when_mirror_disappears(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify a missing mirror stops the wait immediately."""

        def get_mirror_status(_: str) -> MirrorStatusResponse:
            raise MirrorNotFoundException("Mirror 'cdc_one' not found")

        monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)

        with pytest.raises(MirrorFailedException):
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_RUNNING", timeout=5)

    def test_requires_resync_when_initial_setup(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify setup is not accepted as progress when it is the initial status."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_SETUP"))

        with pytest.raises(MirrorTimeoutException):
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_SETUP", timeout=5)

    def test_accepts_resync_then_setup_when_initial_setup(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify a mirror already in setup waits for the drop before accepting."""
        states = iter(["STATUS_RESYNC", "STATUS_SETUP"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))

        assert (
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_SETUP", timeout=5)
            == "STATUS_SETUP"
        )

    def test_completed_initial_returns_immediately(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify completed mirrors skip the start wait."""

        def get_mirror_status(_: str) -> MirrorStatusResponse:
            raise AssertionError("should not poll")

        monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)

        assert (
            peerdb.wait_for_mirror_resync_started("cdc_one", "STATUS_COMPLETED", timeout=5)
            == "STATUS_COMPLETED"
        )

    def test_reports_status_changes(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Verify the callback reports each observed status."""
        states = iter(["STATUS_RESYNC", "STATUS_SETUP"])
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(next(states)))
        seen = []

        peerdb.wait_for_mirror_resync_started(
            "cdc_one",
            "STATUS_RUNNING",
            timeout=5,
            on_status_change=lambda status, _: seen.append(status),
        )

        assert seen == ["STATUS_RESYNC", "STATUS_SETUP"]


class TestResyncMirrorWait:
    """Offline tests for resync request wait behaviour."""

    @pytest.fixture(scope="function")
    def peerdb(self) -> PeerDB:
        """Provide a client that does not contact the server."""
        return PeerDB(Path(__file__).parent / "fixtures" / "peerdb.offline.yaml")

    @pytest.fixture(autouse=True)
    def post_calls(self, monkeypatch: pytest.MonkeyPatch) -> list:
        """Capture resync requests without contacting the server."""
        calls = []

        def post(*args, **kwargs):
            calls.append((args, kwargs))
            response = requests.Response()
            response.status_code = 200
            return response

        monkeypatch.setattr("dw_lib.peerdb.requests.post", post)
        return calls

    @staticmethod
    def _status(flow_state: str) -> MirrorStatusResponse:
        return MirrorStatusResponse(
            createdAt=datetime.datetime.now(datetime.UTC),
            currentFlowState=flow_state,
            flowJobName="cdc_one",
        )

    def test_running_mirror_waits_for_resync_start(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, post_calls: list
    ) -> None:
        """Verify a running mirror waits for the resync to start."""
        calls = []
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_RUNNING"))

        def wait_for_mirror_resync_started(
            flow_job_name: str,
            initial_status: str,
            timeout: int = RESYNC_START_TIMEOUT,
            on_status_change=None,
        ) -> str:
            calls.append((flow_job_name, initial_status, timeout))
            return "STATUS_SETUP"

        monkeypatch.setattr(
            peerdb, "wait_for_mirror_resync_started", wait_for_mirror_resync_started
        )

        response = peerdb.resync_mirror("cdc_one")

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert len(post_calls) == 1
        assert calls == [("cdc_one", "STATUS_RUNNING", RESYNC_START_TIMEOUT)]

    @pytest.mark.parametrize("flow_state", ["STATUS_COMPLETED", "STATUS_FAILED"])
    def test_recreated_mirror_does_not_wait_for_resync(
        self,
        peerdb: PeerDB,
        monkeypatch: pytest.MonkeyPatch,
        post_calls: list,
        flow_state: str,
    ) -> None:
        """Verify completed and failed mirrors are recreated without a start wait."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(flow_state))

        def wait_for_mirror_resync_started(*args, **kwargs) -> str:
            raise AssertionError("should not wait for the resync to start")

        monkeypatch.setattr(
            peerdb, "wait_for_mirror_resync_started", wait_for_mirror_resync_started
        )

        response = peerdb.resync_mirror("cdc_one")

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert len(post_calls) == 1

    def test_no_wait_returns_after_request(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, post_calls: list
    ) -> None:
        """Verify parallel mode returns after the request without observing the start."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_RUNNING"))

        def wait_for_mirror_resync_started(*args, **kwargs) -> str:
            raise AssertionError("should not wait for the resync to start")

        monkeypatch.setattr(
            peerdb, "wait_for_mirror_resync_started", wait_for_mirror_resync_started
        )

        response = peerdb.resync_mirror("cdc_one", wait=False)

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert len(post_calls) == 1

    @pytest.mark.parametrize("flow_state", ["STATUS_TERMINATED", "STATUS_TERMINATING"])
    def test_terminated_mirror_is_rejected(
        self,
        peerdb: PeerDB,
        monkeypatch: pytest.MonkeyPatch,
        post_calls: list,
        flow_state: str,
    ) -> None:
        """Verify terminated mirrors are rejected before a request is sent."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(flow_state))

        with pytest.raises(ResyncMirrorException):
            peerdb.resync_mirror("cdc_one")

        assert post_calls == []

    def test_missing_mirror_is_skipped(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, post_calls: list
    ) -> None:
        """Verify a missing mirror is skipped when if_exists is True."""

        def get_mirror_status(_: str) -> MirrorStatusResponse:
            raise MirrorNotFoundException("Mirror 'cdc_one' not found")

        monkeypatch.setattr(peerdb, "get_mirror_status", get_mirror_status)

        response = peerdb.resync_mirror("cdc_one", if_exists=True)

        assert response.message == "Mirror 'cdc_one' not found, skipping because if_exists=True"
        assert post_calls == []
