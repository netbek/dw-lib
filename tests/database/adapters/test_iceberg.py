from ...asserts import assert_count_equal
from dw_lib import DuckDBAdapter, DuckDBSettings, IcebergAdapter, IcebergSettings
from pyiceberg.table import Table
from typing import Any, Generator

import datetime
import pyarrow
import pytest


class TestIcebergAdapter:
    @pytest.fixture(scope="class")
    def duckdb_adapter(self) -> Generator[DuckDBAdapter, Any, None]:
        yield DuckDBAdapter(DuckDBSettings(database=":memory:", extensions=["iceberg"]))

    @pytest.fixture(scope="class")
    def iceberg_adapter(
        self, iceberg_settings: IcebergSettings
    ) -> Generator[IcebergAdapter, Any, None]:
        iceberg_adapter = IcebergAdapter(iceberg_settings)
        iceberg_adapter.create_namespace(iceberg_settings.namespace)
        yield iceberg_adapter
        iceberg_adapter.drop_namespace(iceberg_settings.namespace, cascade=True)

    @pytest.fixture(scope="function")
    def iceberg_table(self, iceberg_adapter: IcebergAdapter) -> Generator[Table, Any, None]:
        table = "test_table"
        statement = f"""
        create table {table} (
            id bigint,
            updated_at timestamp default now()
        );
        """
        yield iceberg_adapter.create_table(table, statement)
        iceberg_adapter.drop_table(table)

    def test_has_namespace_non_existent(self, iceberg_adapter: IcebergAdapter):
        assert iceberg_adapter.has_namespace("non_existent") is False

    def test_has_namespace_existent(self, iceberg_adapter: IcebergAdapter):
        assert iceberg_adapter.has_namespace(iceberg_adapter.settings.namespace) is True

    def test_has_table_non_existent(self, iceberg_adapter: IcebergAdapter):
        assert iceberg_adapter.has_table("non_existent") is False

    def test_has_table_existent(self, iceberg_adapter: IcebergAdapter, iceberg_table: Table):
        namespace, table = iceberg_table.name()
        assert iceberg_adapter.has_table(table, namespace=namespace) is True

    def test_create_and_drop_table(
        self, iceberg_adapter: IcebergAdapter, duckdb_adapter: DuckDBAdapter
    ):
        table = "test_table"
        statement = f"""
        create table {table} (
            id bigint,
            updated_at timestamp default now()
        );
        """

        # Test that table can be created
        assert iceberg_adapter.has_table(table) is False
        iceberg_table = iceberg_adapter.create_table(table, statement)
        assert iceberg_adapter.has_table(table) is True

        # Test that data can be appended to table
        now = datetime.datetime.now()
        df = pyarrow.Table.from_pylist(
            [
                {"id": 1},
                {"id": 2, "updated_at": now},
            ],
            schema=iceberg_table.schema().as_arrow(),
        )
        iceberg_table.append(df)

        # Test that data can be fetched using PyIceberg
        actual = iceberg_table.scan().to_arrow().to_pylist()
        expected = [
            {"id": 1, "updated_at": None},
            {"id": 2, "updated_at": now},
        ]
        assert_count_equal(actual, expected)

        # Test that data can be fetched using DuckDB
        with duckdb_adapter.create_client() as conn:
            statement = duckdb_adapter.get_create_secret_statement_for_iceberg(
                iceberg_adapter.settings, replace=True
            )
            conn.execute(statement)

            statement = "select * from iceberg_scan(?);"
            actual = (
                conn.query(statement, params=[iceberg_table.metadata_location])
                .to_arrow_table()
                .to_pylist()
            )
        assert_count_equal(actual, expected)

        # Test that table can be dropped
        iceberg_adapter.drop_table(table)
        assert iceberg_adapter.has_table(table) is False

    def test_get_table(self, iceberg_adapter: IcebergAdapter, iceberg_table: Table):
        namespace, table = iceberg_table.name()
        assert iceberg_adapter.get_table(table, namespace=namespace) == iceberg_table

    def test_drop_tables(self, iceberg_adapter: IcebergAdapter, iceberg_table: Table):
        assert_count_equal(iceberg_adapter.list_tables(), [iceberg_table.name()])
        iceberg_adapter.drop_tables()
        assert_count_equal(iceberg_adapter.list_tables(), [])

    def test_list_tables_empty_catalog(self, iceberg_adapter: IcebergAdapter):
        assert_count_equal(iceberg_adapter.list_tables(), [])

    def test_list_tables_populated_catalog(
        self, iceberg_adapter: IcebergAdapter, iceberg_table: Table
    ):
        assert_count_equal(iceberg_adapter.list_tables(), [iceberg_table.name()])
