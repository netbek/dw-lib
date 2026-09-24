from ...asserts import assert_equal_ignoring_whitespace
from ...conftest import DatabaseTest
from collections.abc import Generator
from dw_lib.database import PostgresAdapter, PostgresRelation, PostgresSettings
from dw_lib.exceptions import (
    PublicationNotFoundException,
    TableNotFoundException,
    UserNotFoundException,
)
from sqlalchemy import Table, text
from typing import Any

import pytest


class TestPostgresAdapter(DatabaseTest):
    """Tests for `PostgresAdapter`."""

    @pytest.fixture(scope="function")
    def postgres_user(self, postgres_adapter: PostgresAdapter) -> Generator[str, Any]:
        """Provide a test user and drop it after the test."""
        username = "test_user"
        password = "secret"

        postgres_adapter.create_user(username, password)

        yield username

        postgres_adapter.drop_user(username)

    def test_instantiation_with_sqlalchemy_url(self, postgres_settings: PostgresSettings):
        """Verify an adapter can be built from a SQLAlchemy URL."""
        adapter = PostgresAdapter(postgres_settings.to_sqlalchemy_url())
        assert isinstance(adapter.settings, PostgresSettings)
        assert postgres_settings.model_dump() == adapter.settings.model_dump()

    def test_instantiation_with_string_url(self, postgres_settings: PostgresSettings):
        """Verify an adapter can be built from a string URL."""
        adapter = PostgresAdapter(postgres_settings.to_string(hide_password=False))
        assert isinstance(adapter.settings, PostgresSettings)
        assert postgres_settings.model_dump() == adapter.settings.model_dump()

    @pytest.fixture(scope="function")
    def postgres_table(self, postgres_adapter: PostgresAdapter) -> Generator[Table, Any]:
        """Provide a test table and drop it after the test."""
        table = "test_table"
        statement = f"""
        create table if not exists {PostgresRelation(table=table)} (
            id bigint,
            updated_at timestamp default now()
        );
        """

        postgres_adapter.create_table(table, statement)

        yield postgres_adapter.get_table(table)

        postgres_adapter.drop_table(table)

    @pytest.fixture(scope="function")
    def postgres_publication(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ) -> Generator[str, Any]:
        """Provide a publication over the test table and drop it after the test."""
        publication = "test_publication"

        postgres_adapter.create_publication(publication, tables=[postgres_table.name])

        yield publication

        postgres_adapter.drop_publication(publication)

    def test_create_client(self, postgres_adapter: PostgresAdapter):
        """Verify `create_client` yields a working connection and cursor."""
        with postgres_adapter.create_client() as (_, cur):
            cur.execute(
                "select 1 from information_schema.schemata where catalog_name = %s limit 1;",
                [postgres_adapter.settings.database],
            )
            actual = cur.fetchall()
        assert actual == [(1,)]

    # TODO Turn on this test after separating fixtures for psycopg and psycopg2
    # def test_create_client_psycopg_row_factory(self, postgres_adapter: PostgresAdapter):
    #     from psycopg.rows import dict_row

    #     with postgres_adapter.create_client(row_factory=dict_row) as (conn, cur):
    #         cur.execute(
    #             "select 1 as found from information_schema.schemata where catalog_name = %s limit 1;",
    #             [postgres_adapter.settings.database],
    #         )
    #         actual = cur.fetchall()

    #     assert actual == [{"found": 1}]

    def test_create_client_psycopg2_row_factory(self, postgres_adapter: PostgresAdapter):
        """Verify `create_client` applies the psycopg2 row factory."""
        from psycopg2.extras import RealDictCursor

        with postgres_adapter.create_client(row_factory=RealDictCursor) as (_, cur):
            cur.execute(
                "select 1 as found from information_schema.schemata where catalog_name = %s limit 1;",
                [postgres_adapter.settings.database],
            )
            actual = cur.fetchall()

        assert actual == [{"found": 1}]

    def test_create_session(self, postgres_adapter: PostgresAdapter):
        """Verify `create_session` yields a working SQLAlchemy session."""
        with postgres_adapter.create_session() as session:
            actual = session.execute(
                text(
                    "select 1 from information_schema.schemata where catalog_name = :database limit 1;"
                ).bindparams(database=postgres_adapter.settings.database)
            ).all()
        assert actual == [(1,)]

    def test_can_connect(self, postgres_adapter: PostgresAdapter):
        """Verify `can_connect` is true for a reachable server."""
        assert postgres_adapter.can_connect() is True

    def test_has_database_non_existent(self, postgres_adapter: PostgresAdapter):
        """Verify `has_database` is false for a missing database."""
        assert postgres_adapter.has_database("non_existent") is False

    def test_has_database_existent(self, postgres_adapter: PostgresAdapter):
        """Verify `has_database` is true for an existing database."""
        assert postgres_adapter.has_database(postgres_adapter.settings.database) is True

    def test_has_schema_non_existent(self, postgres_adapter: PostgresAdapter):
        """Verify `has_schema` is false for missing database or schema names."""
        tests = [
            ("non_existent", postgres_adapter.settings.schema_),
            (postgres_adapter.settings.database, "non_existent"),
            ("non_existent", "non_existent"),
        ]

        for database, schema in tests:
            assert postgres_adapter.has_schema(schema, database=database) is False

    def test_has_schema_existent(self, postgres_adapter: PostgresAdapter):
        """Verify `has_schema` is true for an existing schema."""
        assert postgres_adapter.has_schema(postgres_adapter.settings.schema_) is True

    def test_has_table_non_existent(self, postgres_adapter: PostgresAdapter):
        """Verify `has_table` is false for a missing table."""
        assert postgres_adapter.has_table("non_existent") is False

    def test_has_table_existent(self, postgres_adapter: PostgresAdapter, postgres_table: Table):
        """Verify `has_table` is true for an existing table."""
        assert postgres_adapter.has_table(postgres_table.name) is True

    def test_get_table_non_existent(self, postgres_adapter: PostgresAdapter):
        """Verify `get_table` raises for a missing table."""
        with pytest.raises(TableNotFoundException):
            postgres_adapter.get_table("non_existent")

    def test_get_table_existent(self, postgres_adapter: PostgresAdapter, postgres_table: Table):
        """Verify `get_table` returns the table's columns."""
        table = postgres_adapter.get_table(postgres_table.name)
        assert {"id", "updated_at"} == {column.name for column in table.columns}

    def test_create_and_drop_table(self, postgres_adapter: PostgresAdapter):
        """Verify table creation and removal, including `if_exists` handling."""
        table = "test_table"
        statement = f"""
        create table if not exists {PostgresRelation(table=table)} (
            id bigint,
            updated_at timestamp default now()
        );
        """

        assert postgres_adapter.has_table(table) is False

        postgres_adapter.create_table(table, statement)
        assert postgres_adapter.has_table(table) is True

        postgres_adapter.drop_table(table)
        assert postgres_adapter.has_table(table) is False

        with pytest.raises(TableNotFoundException):
            postgres_adapter.drop_table(table)

        assert postgres_adapter.drop_table(table, if_exists=True) is None

    def test_make_create_table_statement_from_table_non_existent(
        self, postgres_adapter: PostgresAdapter
    ):
        """Verify the statement builder raises for a missing table."""
        with pytest.raises(TableNotFoundException):
            postgres_adapter.make_create_table_statement_from_table("non_existent")

    def test_make_create_table_statement_from_table_existent(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify the generated statement matches the source table."""
        actual = postgres_adapter.make_create_table_statement_from_table(postgres_table.name)
        expected = f"""
        CREATE TABLE {postgres_adapter.settings.schema_}.{postgres_table.name} (
            id BIGINT,
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
        """
        assert_equal_ignoring_whitespace(actual, expected)

    def test_list_tables_empty_database(self, postgres_adapter: PostgresAdapter):
        """Verify `list_tables` is empty for an empty database."""
        assert postgres_adapter.list_tables() == []

    def test_list_tables_populated_database(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify `list_tables` returns the database's tables."""
        assert {postgres_table.name} == {table.name for table in postgres_adapter.list_tables()}

    def test_get_table_replica_identity_non_existent(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify `get_table_replica_identity` is None for a missing table."""
        assert postgres_adapter.get_table_replica_identity("non_existent_table") is None

    def test_get_table_replica_identity_existent(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify `get_table_replica_identity` returns the default identity."""
        assert postgres_adapter.get_table_replica_identity(postgres_table.name) == "default"

    def test_set_table_replica_identity_non_existent(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify `set_table_replica_identity` ignores a missing table."""
        postgres_adapter.set_table_replica_identity("non_existent_table", "full")

    def test_set_table_replica_identity_existent(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify `set_table_replica_identity` updates the identity to full."""
        assert postgres_adapter.get_table_replica_identity(postgres_table.name) == "default"
        postgres_adapter.set_table_replica_identity(postgres_table.name, "full")
        assert postgres_adapter.get_table_replica_identity(postgres_table.name) == "full"

    def test_has_user_non_existent_user(self, postgres_adapter: PostgresAdapter):
        """Verify `has_user` is false for a missing user."""
        assert postgres_adapter.has_user("non_existent_user") is False

    def test_has_user_existent_user(self, postgres_adapter: PostgresAdapter):
        """Verify `has_user` is true for an existing user."""
        assert postgres_adapter.has_user(postgres_adapter.settings.username) is True

    def test_create_and_drop_user(self, postgres_adapter: PostgresAdapter):
        """Verify user creation and removal, including `if_exists` handling."""
        username = "test_user"
        password = "secret"

        assert postgres_adapter.has_user(username) is False

        postgres_adapter.create_user(username, password)
        assert postgres_adapter.has_user(username) is True

        postgres_adapter.drop_user(username)
        assert postgres_adapter.has_user(username) is False

        with pytest.raises(UserNotFoundException):
            postgres_adapter.drop_user(username)

        assert postgres_adapter.drop_user(username, if_exists=True) is None

    def test_grant_and_revoke_user_privileges(
        self, postgres_adapter: PostgresAdapter, postgres_user: str, postgres_table: Table
    ):
        """Verify granted privileges appear for the user and revoking clears them."""
        postgres_adapter.grant_user_privileges(postgres_user, postgres_adapter.settings.schema_)

        assert postgres_adapter.list_user_privileges(postgres_user) == [
            (
                postgres_adapter.settings.database,
                postgres_adapter.settings.schema_,
                postgres_table.name,
                "SELECT",
            )
        ]

        postgres_adapter.revoke_user_privileges(postgres_user, postgres_adapter.settings.schema_)

        assert postgres_adapter.list_user_privileges(postgres_user) == []

    def test_create_and_drop_publication(
        self, postgres_adapter: PostgresAdapter, postgres_table: Table
    ):
        """Verify publication creation and removal, including `if_exists` handling."""
        publication = "test_publication"

        postgres_adapter.create_publication(publication, [postgres_table.name])
        assert postgres_adapter.list_publications() == [publication]

        postgres_adapter.drop_publication(publication)
        assert postgres_adapter.list_publications() == []

        with pytest.raises(PublicationNotFoundException):
            postgres_adapter.drop_publication(publication)

        assert postgres_adapter.drop_publication(publication, if_exists=True) is None

    def test_list_publications(self, postgres_adapter: PostgresAdapter, postgres_publication: str):
        """Verify `list_publications` returns the created publication."""
        assert postgres_adapter.list_publications() == [postgres_publication]
