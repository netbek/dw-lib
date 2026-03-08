from ...conftest import DatabaseTest
from dw_lib.database import DuckDBAdapter

# from sqlalchemy import text


class TestDuckDBAdapter(DatabaseTest):
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
