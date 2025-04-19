from ..conftest import PeerDBTest
from collections.abc import Generator
from dw_lib.peerdb import PeerDB
from typing import Any

import os
import pydash
import pytest


class TestIntegration(PeerDBTest):
    @pytest.fixture(scope="function")
    def peerdb_config_path(self, pytestconfig) -> Generator[str, Any, None]:
        yield os.path.join(pytestconfig.rootpath, "tests/peerdb/fixtures/peerdb.postgres.yaml")

    def test_get_and_update_settings(self, peerdb: PeerDB):
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value is None

        peerdb.update_settings({"PEERDB_NULLABLE": "false"})
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "false"

        peerdb.update_settings({"PEERDB_NULLABLE": "true"})
        settings = peerdb.get_settings().settings
        assert pydash.find(settings, lambda x: x.name == "PEERDB_NULLABLE").value == "true"
