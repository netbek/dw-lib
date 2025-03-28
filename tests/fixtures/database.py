from dw_lib.database import ClickHouseAdapter, PostgresAdapter
from dw_lib.types import ClickHouseSettings, PostgresSettings
from typing import Any, Generator

import pytest


class DatabaseTest:
    @pytest.fixture(scope="session")
    def clickhouse_adapter(
        self, clickhouse_settings: ClickHouseSettings
    ) -> Generator[ClickHouseAdapter, Any, None]:
        yield ClickHouseAdapter(clickhouse_settings)

    @pytest.fixture(scope="session")
    def postgres_adapter(
        self, postgres_settings: PostgresSettings
    ) -> Generator[PostgresAdapter, Any, None]:
        yield PostgresAdapter(postgres_settings)
