from dw_lib.exceptions import (
    GetDynamicSettingsException,
    GetMirrorStatusException,
    MirrorTerminalStateException,
    MirrorTimeoutException,
)
from dw_lib.peerdb import MirrorStatusResponse, PeerDB
from pathlib import Path
from types import SimpleNamespace

import datetime
import pytest
import requests


class FakeClock:
    """Deterministic monotonic clock for lifecycle timeout tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make_peerdb(tmp_path: Path, **timeouts: int) -> PeerDB:
    """Write a minimal PeerDB config and return the client."""
    lines = [
        "client:",
        "  peerdb_ui_url: http://localhost:3000",
    ]

    for key, value in timeouts.items():
        lines.append(f"  {key}: {value}")

    config_file = tmp_path / "peerdb.yaml"
    config_file.write_text("\n".join(lines) + "\n")

    return PeerDB(config_file=config_file)


def make_status(status: str, name: str = "mirror") -> MirrorStatusResponse:
    """Return a mirror status response with the given flow state."""
    return MirrorStatusResponse(
        createdAt=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        currentFlowState=status,
        flowJobName=name,
    )


class TestWaitForMirrorStatus:
    """Offline tests for wall-clock mirror status waits."""

    def test_uses_wall_clock_deadline(self, monkeypatch, tmp_path: Path):
        """Verify slow status calls cannot extend the configured timeout."""
        peerdb = make_peerdb(tmp_path, mirror_status_wait_timeout_seconds=5)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)

        calls = 0

        def get_status(name: str) -> MirrorStatusResponse:
            nonlocal calls
            calls += 1
            clock.now += 4
            return make_status("STATUS_SETUP", name)

        monkeypatch.setattr(peerdb, "get_mirror_status", get_status)

        with pytest.raises(MirrorTimeoutException):
            peerdb.wait_for_mirror_status("mirror", {"STATUS_RUNNING"})

        assert calls == 1

    def test_fails_fast_on_terminal_status(self, monkeypatch, tmp_path: Path):
        """Verify a terminal status stops the wait without sleeping."""
        peerdb = make_peerdb(tmp_path)
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: make_status("STATUS_FAILED", name),
        )

        with pytest.raises(MirrorTerminalStateException):
            peerdb.wait_for_mirror_status("mirror", {"STATUS_RUNNING"}, timeout=60)

    def test_recovers_from_transient_error(self, monkeypatch, tmp_path: Path):
        """Verify a transient status error is retried until the deadline."""
        peerdb = make_peerdb(tmp_path, mirror_status_wait_timeout_seconds=5)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)

        calls = 0

        def get_status(name: str) -> MirrorStatusResponse:
            nonlocal calls
            calls += 1

            if calls == 1:
                raise GetMirrorStatusException("temporary")

            return make_status("STATUS_RUNNING", name)

        monkeypatch.setattr(peerdb, "get_mirror_status", get_status)

        assert peerdb.wait_for_mirror_status("mirror", {"STATUS_RUNNING"}) == "STATUS_RUNNING"
        assert calls == 2

    def test_reports_last_error_at_deadline(self, monkeypatch, tmp_path: Path):
        """Verify a persistent status error is included in the timeout."""
        peerdb = make_peerdb(tmp_path, mirror_status_wait_timeout_seconds=2)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: (_ for _ in ()).throw(GetMirrorStatusException("boom")),
        )

        with pytest.raises(MirrorTimeoutException) as exc_info:
            peerdb.wait_for_mirror_status("mirror", {"STATUS_RUNNING"})

        assert "boom" in str(exc_info.value)


class TestMirrorExistence:
    """Offline tests for mirror existence semantics."""

    def test_unknown_status_means_mirror_exists(self, monkeypatch, tmp_path: Path):
        """Verify a successful unknown status means the mirror exists."""
        peerdb = make_peerdb(tmp_path)
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: make_status("STATUS_UNKNOWN", name),
        )

        assert peerdb.has_mirror("mirror") is True


class TestLifecycleTransitions:
    """Offline tests for pause, resume, resync, and drop transitions."""

    def test_pause_from_pausing_waits_for_paused(self, monkeypatch, tmp_path: Path):
        """Verify pause from PAUSING waits for PAUSED."""
        peerdb = make_peerdb(tmp_path, mirror_pause_wait_timeout_seconds=5)
        statuses = iter(["STATUS_PAUSING", "STATUS_PAUSED"])
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: make_status(next(statuses), name),
        )

        response = peerdb.pause_mirror("mirror")

        assert response.message == "Paused mirror 'mirror'"

    def test_resume_from_pausing_waits_for_paused(self, monkeypatch, tmp_path: Path):
        """Verify resume from PAUSING waits for PAUSED before resuming."""
        peerdb = make_peerdb(
            tmp_path,
            mirror_pause_wait_timeout_seconds=5,
            mirror_resume_wait_timeout_seconds=5,
        )
        statuses = iter(["STATUS_PAUSING", "STATUS_PAUSED", "STATUS_RUNNING"])
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: make_status(next(statuses), name),
        )
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        response = peerdb.resume_mirror("mirror")

        assert response.message == "Resumed mirror 'mirror'"

    def test_resync_from_failed_does_not_wait_for_resync(self, monkeypatch, tmp_path: Path):
        """Verify failed mirrors return after the synchronous recreate request."""
        peerdb = make_peerdb(tmp_path)
        calls = 0

        def get_status(name: str) -> MirrorStatusResponse:
            nonlocal calls
            calls += 1
            return make_status("STATUS_FAILED", name)

        monkeypatch.setattr(peerdb, "get_mirror_status", get_status)
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        response = peerdb.resync_mirror("mirror")

        assert calls == 1
        assert "initiated" in response.message

    def test_resync_from_running_waits_for_progress(self, monkeypatch, tmp_path: Path):
        """Verify running mirrors wait for a resync progress status."""
        peerdb = make_peerdb(tmp_path, mirror_resync_wait_timeout_seconds=5)
        statuses = iter(["STATUS_RUNNING", "STATUS_RESYNC"])
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: make_status(next(statuses), name),
        )
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        response = peerdb.resync_mirror("mirror")

        assert "initiated" in response.message

    def test_resync_from_setup_waits_for_resync(self, monkeypatch, tmp_path: Path):
        """Verify a pre-existing SETUP status is not treated as resync progress."""
        peerdb = make_peerdb(tmp_path, mirror_resync_wait_timeout_seconds=5)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)
        statuses = iter(["STATUS_SETUP", "STATUS_SETUP", "STATUS_RESYNC"])
        calls = 0

        def get_status(name: str) -> MirrorStatusResponse:
            nonlocal calls
            calls += 1
            return make_status(next(statuses), name)

        monkeypatch.setattr(peerdb, "get_mirror_status", get_status)
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        response = peerdb.resync_mirror("mirror")

        assert calls == 3
        assert "initiated" in response.message

    def test_resync_from_snapshot_waits_for_resync(self, monkeypatch, tmp_path: Path):
        """Verify a pre-existing SNAPSHOT status is not treated as resync progress."""
        peerdb = make_peerdb(tmp_path, mirror_resync_wait_timeout_seconds=5)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)
        statuses = iter(["STATUS_SNAPSHOT", "STATUS_SNAPSHOT", "STATUS_RESYNC"])
        calls = 0

        def get_status(name: str) -> MirrorStatusResponse:
            nonlocal calls
            calls += 1
            return make_status(next(statuses), name)

        monkeypatch.setattr(peerdb, "get_mirror_status", get_status)
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        response = peerdb.resync_mirror("mirror")

        assert calls == 3
        assert "initiated" in response.message

    def test_resync_from_setup_does_not_accept_running(self, monkeypatch, tmp_path: Path):
        """Verify STATUS_RUNNING alone is not treated as resync progress."""
        peerdb = make_peerdb(tmp_path, mirror_resync_wait_timeout_seconds=1)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)
        calls = 0

        def get_status(name: str) -> MirrorStatusResponse:
            nonlocal calls
            calls += 1

            if calls == 1:
                return make_status("STATUS_SETUP", name)

            return make_status("STATUS_RUNNING", name)

        monkeypatch.setattr(peerdb, "get_mirror_status", get_status)
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        with pytest.raises(MirrorTimeoutException):
            peerdb.resync_mirror("mirror")

    def test_drop_timeout_reports_last_status(self, monkeypatch, tmp_path: Path):
        """Verify a drop timeout includes the last observed mirror status."""
        peerdb = make_peerdb(tmp_path, mirror_drop_wait_timeout_seconds=1)
        clock = FakeClock()
        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: make_status("STATUS_TERMINATING", name),
        )
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        with pytest.raises(MirrorTimeoutException) as exc_info:
            peerdb.drop_mirror("mirror")

        assert "STATUS_TERMINATING" in str(exc_info.value)

    def test_drop_peer_delegates_dependent_mirrors_without_peer_budget(
        self, monkeypatch, tmp_path: Path
    ):
        """Verify dependent mirrors are dropped without a peer-level timeout."""
        peerdb = make_peerdb(tmp_path, mirror_drop_wait_timeout_seconds=7)
        mirrors = [
            SimpleNamespace(
                name="mirror_1",
                source_name="peer",
                destination_name="destination",
            ),
            SimpleNamespace(
                name="mirror_2",
                source_name="source",
                destination_name="peer",
            ),
            SimpleNamespace(
                name="other",
                source_name="source",
                destination_name="destination",
            ),
        ]
        calls = []

        monkeypatch.setattr(
            peerdb,
            "list_mirrors",
            lambda: SimpleNamespace(mirrors=mirrors),
        )
        monkeypatch.setattr(peerdb, "has_peer", lambda name: True)
        monkeypatch.setattr(peerdb, "_request", lambda *args, **kwargs: object())

        def drop_mirrors(names: list[str], **kwargs) -> None:
            calls.append((names, kwargs))

        monkeypatch.setattr(peerdb, "drop_mirrors", drop_mirrors)

        peerdb.drop_peer("peer")

        assert peerdb.config.client.mirror_drop_wait_timeout_seconds == 7
        assert calls == [
            (["mirror_1", "mirror_2"], {"drop_destination_tables": False}),
        ]


class TestRequestTimeouts:
    """Offline tests for request timeout wrapping."""

    def test_get_settings_wraps_read_timeout(self, monkeypatch, tmp_path: Path):
        """Verify a read timeout becomes a library exception."""
        peerdb = make_peerdb(tmp_path)

        def raise_timeout(*args, **kwargs):
            raise requests.ReadTimeout("timed out")

        monkeypatch.setattr("dw_lib.peerdb.requests.request", raise_timeout)

        with pytest.raises(GetDynamicSettingsException):
            peerdb.get_settings()

    def test_can_connect_returns_false_on_read_timeout(self, monkeypatch, tmp_path: Path):
        """Verify the connectivity check returns False on a read timeout."""
        peerdb = make_peerdb(tmp_path)

        def raise_timeout(*args, **kwargs):
            raise requests.ReadTimeout("timed out")

        monkeypatch.setattr("dw_lib.peerdb.requests.get", raise_timeout)

        assert peerdb.can_connect() is False
