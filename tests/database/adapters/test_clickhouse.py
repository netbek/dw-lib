from ...asserts import assert_equal_ignoring_whitespace
from ...conftest import DatabaseTest
from collections.abc import Generator
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.exceptions import (
    DatabaseNotFoundException,
    TableNotFoundException,
    UserNotFoundException,
)
from dw_lib.types import ClickHouseTableIdentifier
from sqlmodel import Table, text
from typing import Any

import pytest


class TestClickHouseAdapter(DatabaseTest):
    @pytest.fixture(scope="function")
    def clickhouse_table(
        self, clickhouse_adapter: ClickHouseAdapter
    ) -> Generator[ClickHouseTableIdentifier, Any, None]:
        table = "test_table"
        statement = f"""
        create or replace table {ClickHouseTableIdentifier(table=table)}
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

    def test_create_url(self, clickhouse_adapter: ClickHouseAdapter):
        url = clickhouse_adapter.create_url(
            host="clickhouse",
            http_port=8123,
            tcp_port=9000,
            username="guest",
            password="secret",
            database="data",
        )
        assert str(url) == "clickhouse://guest:***@clickhouse:8123/data"
        assert (
            url.render_as_string(hide_password=False)
            == "clickhouse://guest:secret@clickhouse:8123/data"
        )

        url = clickhouse_adapter.create_url(
            host="clickhouse",
            http_port=8123,
            tcp_port=9000,
            username="guest",
            password="secret",
            database="data",
            driver="http",
        )
        assert str(url) == "clickhouse+http://guest:***@clickhouse:8123/data"
        assert (
            url.render_as_string(hide_password=False)
            == "clickhouse+http://guest:secret@clickhouse:8123/data"
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
        create or replace table {ClickHouseTableIdentifier(table=table)}
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

    def test_get_create_table_statement(
        self, clickhouse_adapter: ClickHouseAdapter, clickhouse_table: Table
    ):
        with pytest.raises(TableNotFoundException):
            clickhouse_adapter.get_create_table_statement("non_existent")

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
            clickhouse_adapter.get_create_table_statement(clickhouse_table.name), expected
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
