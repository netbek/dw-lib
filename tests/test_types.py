from dw_lib.types import (
    ClickHouseRelation,
    ClickHouseSettings,
    DuckDBSettings,
    HttpUrl,
    PostgresRelation,
    PostgresSettings,
)
from pydantic import ClickHouseDsn, PostgresDsn, ValidationError
from sqlalchemy import make_url, URL

import pytest


class TestHttpUrl:
    @pytest.mark.parametrize(
        "base, path, expected",
        [
            ("https://example.com", "", "https://example.com/"),
            ("https://example.com", "/", "https://example.com/"),
            ("https://example.com", "api", "https://example.com/api"),
            ("https://example.com/", "api", "https://example.com/api"),
            ("https://example.com/api", "v1/users", "https://example.com/api/v1/users"),
            # Leading and trailing slashes
            ("https://example.com", "/api/", "https://example.com/api"),
            ("https://example.com", "//api//v1//users", "https://example.com/api/v1/users"),
            # Check that slashes inside query params aren't collapsed
            (
                "https://example.com",
                "callback?url=https://other.com/login",
                "https://example.com/callback?url=https://other.com/login",
            ),
            # Check that base query params are dropped
            ("https://example.com?auth=true", "api", "https://example.com/api"),
            # Fragment
            ("https://example.com", "api#section1", "https://example.com/api#section1"),
            # Navigation
            ("https://example.com/api/v2", "../v1", "https://example.com/api/v1"),
            ("https://example.com/api/v2", "./users", "https://example.com/api/v2/users"),
            # Security: Prevent domain override
            ("https://example.com", "//evil.com/path", "https://example.com/evil.com/path"),
        ],
    )
    def test_join(self, base, path, expected):
        result = HttpUrl(base).join(path)
        assert str(result) == expected


class TestClickHouseSettings:
    def test_from_url_has_invalid_scheme(self):
        with pytest.raises(ValidationError, match="URL scheme should be"):
            ClickHouseSettings.from_url("clickhouse+foo404://guest:secret@clickhouse:8123/data")

    @pytest.mark.parametrize(
        "url, expected",
        [
            (
                "clickhouse://guest:secret@clickhouse:8123/data",
                {
                    "host": "clickhouse",
                    "http_port": 8123,
                    "tcp_port": None,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "http",
                },
            ),
            (
                "clickhouse://guest:secret@clickhouse:9000/data",
                {
                    "host": "clickhouse",
                    "http_port": None,
                    "tcp_port": 9000,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "native",
                },
            ),
            (
                "clickhouse://guest:secret@clickhouse:9001/data",
                {
                    "host": "clickhouse",
                    "http_port": 9001,
                    "tcp_port": None,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "http",
                },
            ),
            (
                "clickhouse+http://guest:secret@clickhouse:8123/data",
                {
                    "host": "clickhouse",
                    "http_port": 8123,
                    "tcp_port": None,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "http",
                },
            ),
            (
                "clickhouse+http://guest:secret@clickhouse:28123/data",
                {
                    "host": "clickhouse",
                    "http_port": 28123,
                    "tcp_port": None,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "http",
                },
            ),
            (
                "clickhouse+native://guest:secret@clickhouse:9000/data",
                {
                    "host": "clickhouse",
                    "http_port": None,
                    "tcp_port": 9000,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "native",
                },
            ),
            (
                "clickhouse+native://guest:secret@clickhouse:29000/data",
                {
                    "host": "clickhouse",
                    "http_port": None,
                    "tcp_port": 29000,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "driver": "native",
                },
            ),
        ],
    )
    def test_from_url_string(self, url, expected):
        settings = ClickHouseSettings.from_url(url)
        assert settings.model_dump(by_alias=True) == expected

    def test_from_url_sqlalchemy(self):
        url = make_url("clickhouse+http://guest:secret@clickhouse:8123/data")
        settings = ClickHouseSettings.from_url(url)
        assert settings.model_dump(by_alias=True) == {
            "host": "clickhouse",
            "http_port": 8123,
            "tcp_port": None,
            "username": "guest",
            "password": "secret",
            "database": "data",
            "driver": "http",
        }

    def test_from_url_pydantic(self):
        url = ClickHouseDsn("clickhouse+http://guest:secret@clickhouse:8123/data")
        settings = ClickHouseSettings.from_url(url)
        assert settings.model_dump(by_alias=True) == {
            "host": "clickhouse",
            "http_port": 8123,
            "tcp_port": None,
            "username": "guest",
            "password": "secret",
            "database": "data",
            "driver": "http",
        }

    def test_to_sqlalchemy_url(self):
        settings = ClickHouseSettings(
            host="clickhouse",
            http_port=8123,
            tcp_port=9000,
            username="guest",
            password="secret",
            database="data",
            driver="http",
        )
        url = settings.to_sqlalchemy_url()
        assert isinstance(url, URL)
        assert url == make_url("clickhouse+http://guest:secret@clickhouse:8123/data")

    def test_to_string(self):
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
        assert settings.to_string() == "clickhouse+http://guest:***@clickhouse:8123/data"
        assert (
            settings.to_string(hide_password=False)
            == "clickhouse+http://guest:secret@clickhouse:8123/data"
        )


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


class TestPostgresSettings:
    def test_from_url_has_invalid_scheme(self):
        with pytest.raises(ValidationError, match="URL scheme should be"):
            PostgresSettings.from_url("postgresql+foo404://guest:secret@localhost:5432/data")

    @pytest.mark.parametrize(
        "url, expected",
        [
            (
                "postgresql://guest:secret@localhost:5432/data",
                {
                    "host": "localhost",
                    "port": 5432,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "schema": "public",
                    "driver": "psycopg",
                },
            ),
            (
                "postgresql+psycopg://guest:secret@localhost:5432/data",
                {
                    "host": "localhost",
                    "port": 5432,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "schema": "public",
                    "driver": "psycopg",
                },
            ),
            (
                "postgresql+psycopg2://guest:secret@localhost:5432/data",
                {
                    "host": "localhost",
                    "port": 5432,
                    "username": "guest",
                    "password": "secret",
                    "database": "data",
                    "schema": "public",
                    "driver": "psycopg2",
                },
            ),
        ],
    )
    def test_from_url_string(self, url, expected):
        settings = PostgresSettings.from_url(url)
        assert settings.model_dump(by_alias=True) == expected

    def test_from_url_sqlalchemy(self):
        url = make_url("postgresql+psycopg://guest:secret@localhost:5432/data")
        settings = PostgresSettings.from_url(url)
        assert settings.model_dump(by_alias=True) == {
            "host": "localhost",
            "port": 5432,
            "username": "guest",
            "password": "secret",
            "database": "data",
            "schema": "public",
            "driver": "psycopg",
        }

    def test_from_url_pydantic(self):
        url = PostgresDsn("postgresql+psycopg://guest:secret@localhost:5432/data")
        settings = PostgresSettings.from_url(url)
        assert settings.model_dump(by_alias=True) == {
            "host": "localhost",
            "port": 5432,
            "username": "guest",
            "password": "secret",
            "database": "data",
            "schema": "public",
            "driver": "psycopg",
        }

    def test_to_sqlalchemy_url(self):
        settings = PostgresSettings(
            host="localhost",
            port=5432,
            username="guest",
            password="secret",
            database="data",
            driver="psycopg",
        )
        url = settings.to_sqlalchemy_url()
        assert isinstance(url, URL)
        assert url == make_url("postgresql+psycopg://guest:secret@localhost:5432/data")

    def test_to_string(self):
        settings = PostgresSettings(
            host="localhost",
            port=5432,
            username="guest",
            password="secret",
            database="data",
            driver="psycopg",
        )
        assert str(settings) == "postgresql+psycopg://guest:***@localhost:5432/data"
        assert settings.to_string() == "postgresql+psycopg://guest:***@localhost:5432/data"
        assert (
            settings.to_string(hide_password=False)
            == "postgresql+psycopg://guest:secret@localhost:5432/data"
        )


class TestClickHouseRelation:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            ClickHouseRelation()  # ty: ignore[missing-argument]

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
            PostgresRelation()  # ty: ignore[missing-argument]

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
