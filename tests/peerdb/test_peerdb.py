from ..conftest import PeerDBTest
from dw_lib.exceptions import GetDynamicSettingsException, SetDynamicSettingsException
from dw_lib.peerdb import PeerDB
from pathlib import Path

import pydash
import pytest


class TestIntegration(PeerDBTest):
    """Integration tests for `PeerDB` connectivity and settings."""

    @pytest.fixture(scope="function")
    def peerdb_config_path(self) -> Path:
        """Provide the Postgres PeerDB config path."""
        return Path(__file__).parent / "data" / "peerdb.postgres.yaml"

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
        return Path(__file__).parent / "data" / "peerdb.offline.yaml"

    def test_can_connect(self, peerdb: PeerDB):
        """Verify the client reports no connection when services are offline."""
        assert peerdb.can_connect() is False

    def test_get_and_update_settings(self, peerdb: PeerDB):
        """Verify settings access raises when services are offline."""
        with pytest.raises(GetDynamicSettingsException):
            print(peerdb.get_settings().settings)

        with pytest.raises(SetDynamicSettingsException):
            peerdb.update_settings({"PEERDB_NULLABLE": "false"})
