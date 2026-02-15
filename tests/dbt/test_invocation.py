from ..conftest import DatabaseTest
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.dbt import Dbt
from pathlib import Path

import pytest


class TestSeed(DatabaseTest):
    @pytest.fixture
    def profiles_dir(self):
        return Path(__file__).parent / "data" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self):
        return Path(__file__).parent / "data" / "invocation" / "dbt"

    @pytest.fixture
    def otlp_traces_endpoints(self):
        return ["http://localhost:20428/insert/opentelemetry/v1/traces"]

    def test_success(self, clickhouse_adapter: ClickHouseAdapter, profiles_dir, project_dir):
        dbt = Dbt(profiles_dir=profiles_dir, project_dir=project_dir)
        runner_result = dbt.seed()
        assert runner_result.success is True

    def test_success_with_traces(
        self,
        clickhouse_adapter: ClickHouseAdapter,
        victoria_traces,
        profiles_dir,
        project_dir,
        otlp_traces_endpoints,
    ):
        dbt = Dbt(
            profiles_dir=profiles_dir,
            project_dir=project_dir,
            otlp_traces_endpoints=otlp_traces_endpoints,
        )
        runner_result = dbt.seed()
        assert runner_result.success is True
