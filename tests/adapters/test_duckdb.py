# from sqlalchemy import text
from dw import DuckDBAdapter, DuckDBSettings

import pytest


class TestDuckDBAdapter:
    @pytest.fixture(scope="class")
    def duckdb_adapter(self):
        settings = DuckDBSettings(database="/app/temp/test.duckdb")
        yield DuckDBAdapter(settings)

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
                "select 1 from information_schema.schemata where catalog_name = $1 limit 1;",
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
