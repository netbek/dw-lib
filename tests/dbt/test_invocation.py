from ..conftest import DatabaseTest
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.dbt import Dbt
from pathlib import Path

import pytest


class InvocationTest(DatabaseTest):
    @pytest.fixture
    def profiles_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / "dbt"

    @pytest.fixture
    def dbt(self, profiles_dir, project_dir) -> Dbt:
        return Dbt(profiles_dir=profiles_dir, project_dir=project_dir)


class TestRun(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        runner_result = dbt.run()
        assert runner_result.success is True


class TestSeed(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        runner_result = dbt.seed()
        assert runner_result.success is True
