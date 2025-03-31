from ...asserts import assert_count_equal
from dw_lib import IcebergAdapter, IcebergSettings
from pyiceberg.table import Table
from typing import Any, Generator

import pytest


class TestIcebergAdapter:
    @pytest.fixture(scope="class")
    def iceberg_adapter(
        self, iceberg_settings: IcebergSettings
    ) -> Generator[IcebergAdapter, Any, None]:
        iceberg_adapter = IcebergAdapter(iceberg_settings)
        iceberg_adapter.create_namespace(iceberg_settings.namespace)
        yield iceberg_adapter
        iceberg_adapter.drop_namespace(iceberg_settings.namespace)

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

    def test_create_and_drop_table(self, iceberg_adapter: IcebergAdapter):
        table = "test_table"
        statement = f"""
        create table {table} (
            id bigint,
            updated_at timestamp default now()
        );
        """

        assert iceberg_adapter.has_table(table) is False

        iceberg_adapter.create_table(table, statement)
        assert iceberg_adapter.has_table(table) is True

        iceberg_adapter.drop_table(table)
        assert iceberg_adapter.has_table(table) is False

        # t = pa.Table.from_pylist(
        #     [
        #         {
        #             "id": 1,
        #         }
        #     ],
        #     schema=arrow_table_schema,
        # )
        # iceberg_table.append(t)

        # print(iceberg_table.scan(selected_fields=["id"]).to_pandas())

        # with duckdb_adapter.create_client() as conn:
        #     # conn.execute("set unsafe_enable_version_guessing = true;")

        #     conn.execute(
        #         f"describe select id, uuid from iceberg_scan('{warehouse_path}/default.db/{table}/metadata/latest.metadata.json');"
        #     )

        #     print(conn.fetchall())

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
