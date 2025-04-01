# from sqlalchemy import text
from ...asserts import assert_equal_ignoring_whitespace
from dw_lib import DuckDBAdapter, DuckDBSettings, IcebergSettings
from typing import Any, Generator

import pytest


class TestDuckDBAdapter:
    @pytest.fixture(scope="class")
    def duckdb_adapter(
        self, duckdb_settings: DuckDBSettings
    ) -> Generator[DuckDBAdapter, Any, None]:
        yield DuckDBAdapter(duckdb_settings)

    def test_create_url(self, duckdb_adapter: DuckDBAdapter):
        url = duckdb_adapter.create_url(database=":memory:")
        assert str(url) == "duckdb:///:memory:"
        assert url.database == ":memory:"

        url = duckdb_adapter.create_url(database="/path/to/data.duckdb")
        assert str(url) == "duckdb:////path/to/data.duckdb"
        assert url.database == "/path/to/data.duckdb"

    def test_create_client(self, duckdb_adapter: DuckDBAdapter):
        with duckdb_adapter.create_client() as conn:
            conn.execute(
                "select 1 from information_schema.schemata where catalog_name = ? limit 1;",
                ["test"],
            )
            actual = conn.fetchall()
        assert actual == [(1,)]

    # def test_create_session(self, duckdb_adapter: DuckDBAdapter):
    #     with duckdb_adapter.create_session() as session:
    #         actual = session.exec(
    #             text(
    #                 "select 1 from information_schema.schemata where catalog_name = :database limit 1;"
    #             ).bindparams(database="test")
    #         ).all()
    #     assert actual == [(1,)]

    def test_can_connect(self, duckdb_adapter: DuckDBAdapter):
        assert duckdb_adapter.can_connect() is True

    def test_get_create_secret_statement_for_iceberg_http(self, duckdb_adapter: DuckDBAdapter):
        iceberg_settings = IcebergSettings(
            type="sql",
            uri="postgresql+psycopg2://iceberg:iceberg@postgres:5432/iceberg",
            warehouse="s3://iceberg/",
            s3_endpoint="http://minio:9000",
            s3_access_key_id="admin",
            s3_secret_access_key="password",
            s3_region="us-east-1",
            is_minio=True,
        )
        actual = duckdb_adapter.get_create_secret_statement_for_iceberg(iceberg_settings)
        expected = """
create secret s3_secret (
    type s3,
    key_id 'admin',
    secret 'password',
    region 'us-east-1',
    endpoint 'minio:9000',
    url_style 'path',
    use_ssl 'false'
);
"""
        assert_equal_ignoring_whitespace(actual, expected)

    def test_get_create_secret_statement_for_iceberg_https(self, duckdb_adapter: DuckDBAdapter):
        iceberg_settings = IcebergSettings(
            type="sql",
            uri="postgresql+psycopg2://iceberg:iceberg@postgres:5432/iceberg",
            warehouse="s3://iceberg/",
            s3_endpoint="https://minio:9000",
            s3_access_key_id="admin",
            s3_secret_access_key="password",
            s3_region="us-east-1",
            is_minio=True,
        )
        actual = duckdb_adapter.get_create_secret_statement_for_iceberg(iceberg_settings)
        expected = """
create secret s3_secret (
    type s3,
    key_id 'admin',
    secret 'password',
    region 'us-east-1',
    endpoint 'minio:9000',
    url_style 'path',
    use_ssl 'true'
);
"""
        assert_equal_ignoring_whitespace(actual, expected)

    def test_get_create_secret_statement_for_iceberg_replace(self, duckdb_adapter: DuckDBAdapter):
        iceberg_settings = IcebergSettings(
            type="sql",
            uri="postgresql+psycopg2://iceberg:iceberg@postgres:5432/iceberg",
            warehouse="s3://iceberg/",
            s3_endpoint="http://minio:9000",
            s3_access_key_id="admin",
            s3_secret_access_key="password",
            s3_region="us-east-1",
            is_minio=True,
        )
        actual = duckdb_adapter.get_create_secret_statement_for_iceberg(
            iceberg_settings, replace=True
        )
        expected = """
create or replace secret s3_secret (
    type s3,
    key_id 'admin',
    secret 'password',
    region 'us-east-1',
    endpoint 'minio:9000',
    url_style 'path',
    use_ssl 'false'
);
"""
        assert_equal_ignoring_whitespace(actual, expected)
