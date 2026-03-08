from dw_lib.types import (
    ClickHouseRelation,
    ClickHouseSettings,
    DuckDBSettings,
    PostgresRelation,
    PostgresSettings,
)
from pydantic_core import ValidationError

import pytest


class TestClickHouseSettings:
    def test_to_url_and_to_string(self):
        settings = ClickHouseSettings(
            host="clickhouse",
            http_port=8123,
            tcp_port=9000,
            username="guest",
            password="secret",
            database="data",
        )
        assert str(settings) == "clickhouse://guest:***@clickhouse:8123/data"
        assert (
            settings.to_string(hide_password=False)
            == "clickhouse://guest:secret@clickhouse:8123/data"
        )

        settings = ClickHouseSettings(
            host="clickhouse",
            http_port=8123,
            tcp_port=9000,
            username="guest",
            password="secret",
            database="data",
            driver="http",
        )
        assert str(settings) == "clickhouse+http://guest:***@clickhouse:8123/data"
        assert (
            settings.to_string(hide_password=False)
            == "clickhouse+http://guest:secret@clickhouse:8123/data"
        )


class TestDuckDBSettings:
    def test_to_url_and_to_string(self):
        settings = DuckDBSettings(database=":memory:")
        assert str(settings) == "duckdb:///:memory:"
        assert settings.to_url().database == ":memory:"

        settings = DuckDBSettings(database="/path/to/data.duckdb")
        assert str(settings) == "duckdb:////path/to/data.duckdb"
        assert settings.to_url().database == "/path/to/data.duckdb"


class TestPostgresSettings:
    def test_to_url_and_to_string(self):
        settings = PostgresSettings(
            host="localhost", port=5432, username="guest", password="secret", database="data"
        )
        assert str(settings) == "postgresql://guest:***@localhost:5432/data"
        assert (
            settings.to_string(hide_password=False)
            == "postgresql://guest:secret@localhost:5432/data"
        )


class TestClickHouseRelation:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            ClickHouseRelation()

    def test_from_string_database_and_table(self):
        relation = ClickHouseRelation.from_string("my_database.my_table")
        assert relation.database == "my_database"
        assert relation.table == "my_table"

    def test_from_string_table(self):
        relation = ClickHouseRelation.from_string("my_table")
        assert relation.database is None
        assert relation.table == "my_table"

    def test_from_string_empty_string(self):
        with pytest.raises(ValueError):
            ClickHouseRelation.from_string("")

    def test_to_string_database_and_table(self):
        relation = ClickHouseRelation(database="my_database", table="my_table")
        assert str(relation) == "my_database.my_table"

    def test_to_string_table(self):
        relation = ClickHouseRelation(table="my_table")
        assert str(relation) == "my_table"


class TestPostgresRelation:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            PostgresRelation()

    def test_from_string_database_and_schema_and_table(self):
        relation = PostgresRelation.from_string("my_database.my_schema.my_table")
        assert relation.database == "my_database"
        assert relation.schema_ == "my_schema"
        assert relation.table == "my_table"

    def test_from_string_schema_and_table(self):
        relation = PostgresRelation.from_string("my_schema.my_table")
        assert relation.database is None
        assert relation.schema_ == "my_schema"
        assert relation.table == "my_table"

    def test_from_string_table(self):
        relation = PostgresRelation.from_string("my_table")
        assert relation.database is None
        assert relation.schema_ is None
        assert relation.table == "my_table"

    def test_from_string_empty_string(self):
        with pytest.raises(ValueError):
            PostgresRelation.from_string("")

    def test_to_string_database_and_schema_and_table(self):
        relation = PostgresRelation(database="my_database", schema_="my_schema", table="my_table")
        assert str(relation) == "my_database.my_schema.my_table"

    def test_to_string_schema_and_table(self):
        relation = PostgresRelation(schema_="my_schema", table="my_table")
        assert str(relation) == "my_schema.my_table"

    def test_to_string_table(self):
        relation = PostgresRelation(table="my_table")
        assert str(relation) == "my_table"
