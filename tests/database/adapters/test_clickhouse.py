from ...asserts import assert_equal_ignoring_whitespace, assert_sql_equal
from ...conftest import (
    DatabaseTest,
    TableWithoutSchema,
    TableWithSchema,
    ViewWithoutSchema,
    ViewWithSchema,
)
from collections.abc import Generator
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.exceptions import (
    DatabaseNotFoundException,
    TableNotFoundException,
    UserNotFoundException,
)
from dw_lib.types import ClickHouseRelation, ClickHouseSettings
from sqlmodel import Table, text
from typing import Any

import pytest


class TestClickHouseAdapter(DatabaseTest):
    @pytest.fixture(scope="function")
    def clickhouse_table(
        self, clickhouse_adapter: ClickHouseAdapter
    ) -> Generator[ClickHouseRelation, Any, None]:
        table = "test_table"
        statement = f"""
        create or replace table {ClickHouseRelation(table=table)}
        (
            id UInt64,
            updated_at DateTime default now()
        )
        engine = MergeTree
        order by id
        """

        clickhouse_adapter.create_table(table, statement)

        yield clickhouse_adapter.get_table(table)

        clickhouse_adapter.drop_table(table)

    def test_instantiation_with_url(self, clickhouse_settings: ClickHouseSettings):
        adapter = ClickHouseAdapter(clickhouse_settings.to_url())
        assert isinstance(adapter.settings, ClickHouseSettings)
        # Exclude tcp_port from assertion because its value is lost when casting as URL with http driver
        assert clickhouse_settings.model_dump(exclude=["tcp_port"]) == adapter.settings.model_dump(
            exclude=["tcp_port"]
        )

    def test_instantiation_with_string_url(self, clickhouse_settings: ClickHouseSettings):
        adapter = ClickHouseAdapter(clickhouse_settings.to_string(hide_password=False))
        assert isinstance(adapter.settings, ClickHouseSettings)
        # Exclude tcp_port from assertion because its value is lost when casting as string URL with http driver
        assert clickhouse_settings.model_dump(exclude=["tcp_port"]) == adapter.settings.model_dump(
            exclude=["tcp_port"]
        )

    def test_create_client(self, clickhouse_adapter: ClickHouseAdapter):
        with clickhouse_adapter.create_client() as client:
            actual = client.query(
                "select 1 from system.databases where name = {database:String};",
                parameters={"database": clickhouse_adapter.settings.database},
            ).result_rows
        assert actual == [(1,)]

    def test_create_session(self, clickhouse_adapter: ClickHouseAdapter):
        with clickhouse_adapter.create_session() as session:
            actual = session.exec(
                text("select 1 from system.databases where name = :database;").bindparams(
                    database=clickhouse_adapter.settings.database
                )
            ).all()
        assert actual == [(1,)]

    def test_can_connect(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.can_connect() is True

    def test_has_database_non_existent(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.has_database("non_existent") is False

    def test_has_database_existent(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.has_database(clickhouse_adapter.settings.database) is True

    def test_create_and_drop_database(self, clickhouse_adapter: ClickHouseAdapter):
        database = "test_database"

        assert clickhouse_adapter.has_database(database) is False

        clickhouse_adapter.create_database(database)
        assert clickhouse_adapter.has_database(database) is True

        clickhouse_adapter.drop_database(database)
        assert clickhouse_adapter.has_database(database) is False

        with pytest.raises(DatabaseNotFoundException):
            clickhouse_adapter.drop_database(database)

        assert clickhouse_adapter.drop_database(database, if_exists=True) is None

    def test_has_table_non_existent(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.has_table("non_existent") is False

    def test_has_table_existent(
        self, clickhouse_adapter: ClickHouseAdapter, clickhouse_table: Table
    ):
        assert clickhouse_adapter.has_table(clickhouse_table.name) is True

    def test_get_table_non_existent(self, clickhouse_adapter: ClickHouseAdapter):
        with pytest.raises(TableNotFoundException):
            clickhouse_adapter.get_table("non_existent")

    def test_get_table_existent(
        self, clickhouse_adapter: ClickHouseAdapter, clickhouse_table: Table
    ):
        table = clickhouse_adapter.get_table(clickhouse_table.name)
        assert {"id", "updated_at"} == {column.name for column in table.columns}

    def test_create_and_drop_table(self, clickhouse_adapter: ClickHouseAdapter):
        table = "test_table"
        statement = f"""
        create or replace table {ClickHouseRelation(table=table)}
        (
            id UInt64,
            updated_at DateTime default now()
        )
        engine = MergeTree
        order by id
        """

        assert clickhouse_adapter.has_table(table) is False

        clickhouse_adapter.create_table(table, statement)
        assert clickhouse_adapter.has_table(table) is True

        clickhouse_adapter.drop_table(table)
        assert clickhouse_adapter.has_table(table) is False

        with pytest.raises(TableNotFoundException):
            clickhouse_adapter.drop_table(table)

        assert clickhouse_adapter.drop_table(table, if_exists=True) is None

    def test_make_create_table_statement_from_table(
        self, clickhouse_adapter: ClickHouseAdapter, clickhouse_table: Table
    ):
        with pytest.raises(TableNotFoundException):
            clickhouse_adapter.make_create_table_statement_from_table("non_existent")

        expected = f"""
        CREATE TABLE {clickhouse_adapter.settings.database}.{clickhouse_table.name}
        (
            `id` UInt64,
            `updated_at` DateTime DEFAULT now()
        )
        ENGINE = MergeTree
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_equal_ignoring_whitespace(
            clickhouse_adapter.make_create_table_statement_from_table(clickhouse_table.name),
            expected,
        )

    def test_list_tables_empty_database(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.list_tables() == []

    def test_list_tables_populated_database(
        self, clickhouse_adapter: ClickHouseAdapter, clickhouse_table: Table
    ):
        assert {clickhouse_table.name} == {table.name for table in clickhouse_adapter.list_tables()}

    def test_has_user_non_existent_user(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.has_user("non_existent_user") is False

    def test_has_user_existent_user(self, clickhouse_adapter: ClickHouseAdapter):
        assert clickhouse_adapter.has_user(clickhouse_adapter.settings.username) is True

    def test_create_and_drop_user(self, clickhouse_adapter: ClickHouseAdapter):
        username = "test_user"
        password = "secret"

        assert clickhouse_adapter.has_user(username) is False

        clickhouse_adapter.create_user(username, password)
        assert clickhouse_adapter.has_user(username) is True

        clickhouse_adapter.drop_user(username)
        assert clickhouse_adapter.has_user(username) is False

        with pytest.raises(UserNotFoundException):
            clickhouse_adapter.drop_user(username)

        assert clickhouse_adapter.drop_user(username, if_exists=True) is None


class TestTableWithoutSchema(DatabaseTest):
    @pytest.fixture(scope="function")
    def model(self):
        return TableWithoutSchema

    def test_defaults(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(model)
        expected = """
        CREATE TABLE table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_if_not_exists(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, if_not_exists=True
        )
        expected = """
        CREATE TABLE IF NOT EXISTS table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_replace(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(model, replace=True)
        expected = """
        CREATE OR REPLACE TABLE table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_if_not_exists_and_replace(self, clickhouse_adapter: ClickHouseAdapter, model):
        with pytest.raises(ValueError):
            clickhouse_adapter.make_create_table_statement_from_model(
                model, if_not_exists=True, replace=True
            )

    def test_sql_query(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, sql="SELECT 42 AS id"
        )
        expected = """
        CREATE TABLE table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_sql_cte(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, sql="WITH final AS (SELECT 42 AS id) SELECT * FROM final"
        )
        expected = """
        CREATE TABLE table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        AS WITH final AS (SELECT 42 AS id) SELECT * FROM final
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(model, table="my_table")
        expected = """
        CREATE TABLE my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, database="my_database"
        )
        expected = """
        CREATE TABLE my_database.table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, database="my_database", table="my_table"
        )
        expected = """
        CREATE TABLE my_database.my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)


class TestTableWithSchema(DatabaseTest):
    @pytest.fixture(scope="function")
    def model(self):
        return TableWithSchema

    def test_defaults(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(model)
        expected = """
        CREATE TABLE analytics.table_with_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(model, table="my_table")
        expected = """
        CREATE TABLE analytics.my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, database="my_database"
        )
        expected = """
        CREATE TABLE my_database.table_with_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_table_statement_from_model(
            model, database="my_database", table="my_table"
        )
        expected = """
        CREATE TABLE my_database.my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)


class TestViewWithoutSchema(DatabaseTest):
    @pytest.fixture(scope="function")
    def model(self):
        return ViewWithoutSchema

    def test_defaults(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(model, model.__sql__)
        expected = """
        CREATE VIEW view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_if_not_exists(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, if_not_exists=True
        )
        expected = """
        CREATE VIEW IF NOT EXISTS view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_replace(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, replace=True
        )
        expected = """
        CREATE OR REPLACE VIEW view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_if_not_exists_and_replace(self, clickhouse_adapter: ClickHouseAdapter, model):
        with pytest.raises(ValueError):
            clickhouse_adapter.make_create_view_statement_from_model(
                model, model.__sql__, if_not_exists=True, replace=True
            )

    def test_sql_cte(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, "WITH final AS (SELECT 42 AS id) SELECT * FROM final"
        )
        expected = """
        CREATE VIEW view_without_schema
        AS WITH final AS (SELECT 42 AS id) SELECT * FROM final
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, table="my_view"
        )
        expected = """
        CREATE VIEW my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, database="my_database"
        )
        expected = """
        CREATE VIEW my_database.view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, database="my_database", table="my_view"
        )
        expected = """
        CREATE VIEW my_database.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)


class TestViewWithSchema(DatabaseTest):
    @pytest.fixture(scope="function")
    def model(self):
        return ViewWithSchema

    def test_defaults(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(model, model.__sql__)
        expected = """
        CREATE VIEW analytics.view_with_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, table="my_view"
        )
        expected = """
        CREATE VIEW analytics.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, database="my_database"
        )
        expected = """
        CREATE VIEW my_database.view_with_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = clickhouse_adapter.make_create_view_statement_from_model(
            model, model.__sql__, database="my_database", table="my_view"
        )
        expected = """
        CREATE VIEW my_database.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)
