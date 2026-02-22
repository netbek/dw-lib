from ..conftest import PeerDBTest
from dw_lib.peerdb import PeerDB
from pathlib import Path

import pydash
import pytest


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
