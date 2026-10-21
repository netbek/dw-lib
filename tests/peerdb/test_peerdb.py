from ..conftest import PeerDBTest
from dw_lib.exceptions import (
    GetDynamicSettingsException,
    MirrorFailedException,
    MirrorNotFoundException,
    ResyncMirrorException,
    SetDynamicSettingsException,
)
from dw_lib.peerdb import MirrorStatusResponse, PeerDB
from pathlib import Path

import datetime
import pydash
import pytest
import requests


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

    def test_running_mirror_waits_for_resync(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, post_calls: list
    ) -> None:
        """Verify a running mirror waits for the resync to be observed."""
        calls = []
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_RUNNING"))

        def wait_for_mirror_status(
            flow_job_name: str, target_statuses: set[str], timeout: int | None = None
        ) -> str:
            calls.append((flow_job_name, target_statuses, timeout))
            return "STATUS_RESYNC"

        monkeypatch.setattr(peerdb, "wait_for_mirror_status", wait_for_mirror_status)

        response = peerdb.resync_mirror("cdc_one")

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert len(post_calls) == 1
        assert calls == [("cdc_one", {"STATUS_RESYNC"}, None)]

    @pytest.mark.parametrize("flow_state", ["STATUS_COMPLETED", "STATUS_FAILED"])
    def test_recreated_mirror_does_not_wait_for_resync(
        self,
        peerdb: PeerDB,
        monkeypatch: pytest.MonkeyPatch,
        post_calls: list,
        flow_state: str,
    ) -> None:
        """Verify completed and failed mirrors are recreated without waiting for STATUS_RESYNC."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status(flow_state))

        def wait_for_mirror_status(*args, **kwargs) -> str:
            raise AssertionError("should not wait for STATUS_RESYNC")

        monkeypatch.setattr(peerdb, "wait_for_mirror_status", wait_for_mirror_status)

        response = peerdb.resync_mirror("cdc_one")

        assert response.message == "Resync of mirror 'cdc_one' has been initiated"
        assert len(post_calls) == 1

    def test_no_wait_returns_after_request(
        self, peerdb: PeerDB, monkeypatch: pytest.MonkeyPatch, post_calls: list
    ) -> None:
        """Verify parallel mode returns after the request without observing STATUS_RESYNC."""
        monkeypatch.setattr(peerdb, "get_mirror_status", lambda _: self._status("STATUS_RUNNING"))

        def wait_for_mirror_status(*args, **kwargs) -> str:
            raise AssertionError("should not wait for STATUS_RESYNC")

        monkeypatch.setattr(peerdb, "wait_for_mirror_status", wait_for_mirror_status)

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
