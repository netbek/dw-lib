from ..conftest import LoaderTest
from collections.abc import Generator
from dw_lib.database.adapters import PostgresAdapter
from dw_lib.loader import Loader
from pathlib import Path
from sqlmodel import Table
from typing import Any

import pytest

table_defs = [
    (
        "table_1",
        """
        create table table_1 (
            id bigint,
            username text,
            password text,
            age smallint,
            modified_at timestamp(6)
        );
        """,
    ),
    (
        "table_2",
        """
        create table table_2 (
            id bigint,
            longitude double precision,
            latitude double precision,
            is_secret boolean,
            modified_at timestamp(6)
        );
        """,
    ),
    (
        "table_3",
        """
        create table table_3 (
            id bigint,
            ts timestamp(6),
            modified_at timestamp(6)
        );
        """,
    ),
]


class TestIntegration(LoaderTest):
    @pytest.fixture(scope="function")
    def loader_config_path(self) -> Path:
        return Path(__file__).parent / "data" / "loader.postgres.yaml"

    @pytest.fixture(scope="function")
    def all_postgres_tables(
        self, postgres_adapter: PostgresAdapter
    ) -> Generator[list[Table], Any, None]:
        for table_def in table_defs:
            postgres_adapter.create_table(*table_def)

        # Create all tables
        table_names = [table_def[0] for table_def in table_defs]
        tables = [table for table in postgres_adapter.list_tables() if table.name in table_names]

        yield tables

        for table_name in table_names:
            postgres_adapter.drop_table(table_name)

    def test_debug(self, loader: Loader):
        actual = loader.debug()
        expected = {
            "source_1": {
                "URL": "postgresql://postgres:***@localhost:25432/test",
                "Connection test": True,
            },
            "destination_1": {
                "URL": "s3://loader",
                "Connection test": True,
            },
        }
        assert actual == expected

    def test_run(self, all_postgres_tables: list[Table], loader: Loader):
        response = loader.run("source_1", "destination_1", "public.table_1")
        assert (
            response.message == "Copied table 'public.table_1' from 'source_1' to 'destination_1'"
        )
