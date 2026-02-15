from ..conftest import DatabaseTest
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.dbt import Dbt
from pathlib import Path

profiles_dir = Path(__file__).parent / "data" / "invocation" / ".dbt"
project_dir = Path(__file__).parent / "data" / "invocation" / "dbt"


class TestSeed(DatabaseTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter):
        dbt = Dbt(profiles_dir=profiles_dir, project_dir=project_dir)
        runner_result = dbt.seed()
        assert runner_result.success is True

    def test_success_with_traces(self, clickhouse_adapter: ClickHouseAdapter, victoria_traces):
        dbt = Dbt(profiles_dir=profiles_dir, project_dir=project_dir)
        runner_result = dbt.seed()
        assert runner_result.success is True
