from dw_lib.exceptions import MirrorNotFoundException, MirrorTerminalStateException
from dw_lib.peerdb import PeerDB
from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeClock:
    """Deterministic monotonic clock for no-deadline tests."""

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


class TestSerialCreate:
    """Offline tests for serial mirror creation."""

    def test_waits_for_each_mirror_before_creating_the_next(self, monkeypatch, tmp_path: Path):
        """Verify create waits for a mirror to settle before the next create."""
        peerdb = make_peerdb(tmp_path)
        calls = []

        def create_mirror(mirror: dict, if_exists: str = "fail") -> SimpleNamespace:
            calls.append(("create", mirror["flow_job_name"]))
            return SimpleNamespace(message=f"Created mirror '{mirror['flow_job_name']}'")

        def wait_for_mirror_settled(name: str) -> str:
            calls.append(("wait", name))
            return "STATUS_RUNNING"

        monkeypatch.setattr(peerdb, "create_mirror", create_mirror)
        monkeypatch.setattr(peerdb, "wait_for_mirror_settled", wait_for_mirror_settled)

        responses = peerdb.create_mirrors(
            [{"flow_job_name": "one"}, {"flow_job_name": "two"}],
            if_exists="keep",
        )

        assert [response.message for response in responses] == [
            "Created mirror 'one'",
            "Created mirror 'two'",
        ]
        assert calls == [
            ("create", "one"),
            ("wait", "one"),
            ("create", "two"),
            ("wait", "two"),
        ]

    def test_stops_after_the_first_failure(self, monkeypatch, tmp_path: Path):
        """Verify create stops before starting later mirrors after an error."""
        peerdb = make_peerdb(tmp_path)
        calls = []

        def create_mirror(mirror: dict, if_exists: str = "fail") -> SimpleNamespace:
            calls.append(mirror["flow_job_name"])

            if mirror["flow_job_name"] == "one":
                raise RuntimeError("boom")

            return SimpleNamespace(message="created")

        monkeypatch.setattr(peerdb, "create_mirror", create_mirror)

        with pytest.raises(RuntimeError, match="boom"):
            peerdb.create_mirrors(
                [{"flow_job_name": "one"}, {"flow_job_name": "two"}],
            )

        assert calls == ["one"]


class TestSerialDrop:
    """Offline tests for serial mirror drops."""

    def test_delegates_in_order(self, monkeypatch, tmp_path: Path):
        """Verify drop delegates each mirror in order."""
        peerdb = make_peerdb(tmp_path)
        calls = []

        def drop_mirror(name: str, **kwargs) -> SimpleNamespace:
            calls.append((name, kwargs))
            return SimpleNamespace(message=f"Dropped mirror '{name}'")

        monkeypatch.setattr(peerdb, "drop_mirror", drop_mirror)

        responses = peerdb.drop_mirrors(
            ["one", "two"],
            drop_destination_tables=True,
            if_exists=True,
        )

        assert [response.message for response in responses] == [
            "Dropped mirror 'one'",
            "Dropped mirror 'two'",
        ]
        assert calls == [
            ("one", {"drop_destination_tables": True, "if_exists": True}),
            ("two", {"drop_destination_tables": True, "if_exists": True}),
        ]


class TestSerialPauseResume:
    """Offline tests for serial pause and resume."""

    @pytest.mark.parametrize(
        ("batch_method", "single_method", "message"),
        [
            ("pause_mirrors", "pause_mirror", "Paused"),
            ("resume_mirrors", "resume_mirror", "Resumed"),
        ],
    )
    def test_delegates_in_order(
        self, monkeypatch, tmp_path: Path, batch_method: str, single_method: str, message: str
    ):
        """Verify pause and resume delegate each mirror in order."""
        peerdb = make_peerdb(tmp_path)
        calls = []

        def single(name: str) -> SimpleNamespace:
            calls.append(name)
            return SimpleNamespace(message=f"{message} mirror '{name}'")

        monkeypatch.setattr(peerdb, single_method, single)

        responses = getattr(peerdb, batch_method)(["one", "two"])

        assert [response.message for response in responses] == [
            f"{message} mirror 'one'",
            f"{message} mirror 'two'",
        ]
        assert calls == ["one", "two"]


class TestSerialResync:
    """Offline tests for serial mirror resync."""

    def test_waits_for_each_mirror_before_resyncing_the_next(self, monkeypatch, tmp_path: Path):
        """Verify resync waits for a mirror to settle before the next resync."""
        peerdb = make_peerdb(tmp_path)
        calls = []

        def resync_mirror(name: str, if_exists: bool = False) -> SimpleNamespace:
            calls.append(("resync", name))
            return SimpleNamespace(message=f"Resync of mirror '{name}' has been initiated")

        def wait_for_mirror_settled(name: str) -> str:
            calls.append(("wait", name))
            return "STATUS_RUNNING"

        monkeypatch.setattr(peerdb, "resync_mirror", resync_mirror)
        monkeypatch.setattr(peerdb, "wait_for_mirror_settled", wait_for_mirror_settled)

        responses = peerdb.resync_mirrors(["one", "two"], if_exists=True)

        assert [response.message for response in responses] == [
            "Resync of mirror 'one' has been initiated",
            "Resync of mirror 'two' has been initiated",
        ]
        assert calls == [
            ("resync", "one"),
            ("wait", "one"),
            ("resync", "two"),
            ("wait", "two"),
        ]

    def test_skips_missing_mirror_when_if_exists(self, monkeypatch, tmp_path: Path):
        """Verify a missing mirror is skipped without a settle wait."""
        peerdb = make_peerdb(tmp_path)

        monkeypatch.setattr(
            peerdb,
            "resync_mirror",
            lambda name, if_exists=False: SimpleNamespace(
                message=f"Mirror '{name}' not found, skipping because if_exists=True"
            ),
        )

        def wait_for_mirror_settled(name: str) -> str:
            raise MirrorNotFoundException(f"Mirror '{name}' not found")

        monkeypatch.setattr(peerdb, "wait_for_mirror_settled", wait_for_mirror_settled)

        responses = peerdb.resync_mirrors(["missing"], if_exists=True)

        assert len(responses) == 1

    def test_raises_missing_mirror_when_not_if_exists(self, monkeypatch, tmp_path: Path):
        """Verify a missing mirror raises when if_exists is false."""
        peerdb = make_peerdb(tmp_path)

        monkeypatch.setattr(
            peerdb,
            "resync_mirror",
            lambda name, if_exists=False: SimpleNamespace(message="initiated"),
        )

        def wait_for_mirror_settled(name: str) -> str:
            raise MirrorNotFoundException(f"Mirror '{name}' not found")

        monkeypatch.setattr(peerdb, "wait_for_mirror_settled", wait_for_mirror_settled)

        with pytest.raises(MirrorNotFoundException):
            peerdb.resync_mirrors(["missing"])


class TestWaitForMirrorSettled:
    """Offline tests for the no-deadline settle wait."""

    def test_polls_through_snapshot_without_a_deadline(self, monkeypatch, tmp_path: Path):
        """Verify the settle wait continues past setup and snapshot states."""
        peerdb = make_peerdb(tmp_path, mirror_status_wait_timeout_seconds=1)
        clock = FakeClock()
        statuses = iter(["STATUS_SETUP", "STATUS_SNAPSHOT", "STATUS_RUNNING"])

        monkeypatch.setattr("dw_lib.peerdb.time.monotonic", clock.monotonic)
        monkeypatch.setattr("dw_lib.peerdb.time.sleep", clock.sleep)
        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: SimpleNamespace(current_flow_state=next(statuses)),
        )

        assert peerdb.wait_for_mirror_settled("mirror") == "STATUS_RUNNING"

    def test_fails_on_terminal_state(self, monkeypatch, tmp_path: Path):
        """Verify a terminal state stops the settle wait."""
        peerdb = make_peerdb(tmp_path)

        monkeypatch.setattr(
            peerdb,
            "get_mirror_status",
            lambda name: SimpleNamespace(current_flow_state="STATUS_FAILED"),
        )

        with pytest.raises(MirrorTerminalStateException):
            peerdb.wait_for_mirror_settled("mirror")
