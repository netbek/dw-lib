from ...conftest import DatabaseTest
from dw_lib.database import DuckDBAdapter, DuckDBSettings

# from sqlalchemy import text


class TestDuckDBSettings:
    def test_from_url_has_memory_database(self):
        settings = DuckDBSettings.from_url("duckdb:///:memory:")
        assert settings.database == ":memory:"

    def test_from_url_has_file_database(self):
        settings = DuckDBSettings.from_url("duckdb:////path/to/data.duckdb")
        assert settings.database == "/path/to/data.duckdb"

    def test_to_string(self):
        settings = DuckDBSettings(database=":memory:")
        assert str(settings) == "duckdb:///:memory:"
        assert settings.to_string() == "duckdb:///:memory:"
        assert settings.to_sqlalchemy_url().database == ":memory:"

        settings = DuckDBSettings(database="/path/to/data.duckdb")
        assert str(settings) == "duckdb:////path/to/data.duckdb"
        assert settings.to_string() == "duckdb:////path/to/data.duckdb"
        assert settings.to_sqlalchemy_url().database == "/path/to/data.duckdb"


class TestDuckDBAdapter(DatabaseTest):
    def test_instantiation_with_sqlalchemy_url(self, duckdb_settings: DuckDBSettings):
        adapter = DuckDBAdapter(duckdb_settings.to_sqlalchemy_url())
        assert isinstance(adapter.settings, DuckDBSettings)
        assert str(duckdb_settings.database) == adapter.settings.database

    def test_instantiation_with_string_url(self, duckdb_settings: DuckDBSettings):
        adapter = DuckDBAdapter(duckdb_settings.to_string(hide_password=False))
        assert isinstance(adapter.settings, DuckDBSettings)
        assert str(duckdb_settings.database) == adapter.settings.database

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
