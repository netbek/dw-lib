from dw_lib import IcebergAdapter, IcebergSettings
from typing import Any, Generator

import pytest
import re


def get_version_from_path(path):
    match = re.search(r"/metadata/([\w-]+)\.metadata\.json", path)
    if match:
        return match.group(1)


class TestIcebergAdapter:
    @pytest.fixture(scope="class")
    def iceberg_adapter(
        self, iceberg_settings: IcebergSettings
    ) -> Generator[IcebergAdapter, Any, None]:
        yield IcebergAdapter(iceberg_settings.find_catalog("default"))

    @pytest.fixture(scope="function")
    def iceberg_namespace(self, iceberg_adapter: IcebergAdapter) -> Generator[str, Any, None]:
        namespace = "default"
        iceberg_adapter.create_namespace(namespace)
        yield namespace
        iceberg_adapter.drop_namespace(namespace)

    def test_create_table(self, iceberg_adapter: IcebergAdapter, iceberg_namespace: str):
        table = "test_table"
        statement = f"""
        create table if not exists {table} (
            id bigint,
            updated_at timestamp default now()
        );
        """

        assert iceberg_adapter.has_table(table, namespace=iceberg_namespace) is False

        iceberg_adapter.create_table(table, statement, namespace=iceberg_namespace)
        assert iceberg_adapter.has_table(table, namespace=iceberg_namespace) is True

        iceberg_adapter.drop_table(table, namespace=iceberg_namespace)
        assert iceberg_adapter.has_table(table, namespace=iceberg_namespace) is False

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
