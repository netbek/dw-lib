from ..asserts import assert_list_of_dicts_equal_ignore_order
from dw import DuckDBAdapter, PostgresAdapter, Zinc, ZincSettings
from typing import Any, Generator

import psycopg2
import pytest
import re
import yaml


class TestCanConnect:
    @pytest.fixture(scope="function")
    def settings(self) -> Generator[ZincSettings, Any, None]:
        with open("/app/tests/zinc/fixtures/basic_settings.yaml", "rt") as fp:
            settings = yaml.safe_load(fp)
        yield ZincSettings(**settings)

    def test_valid_peers(self, settings: ZincSettings):
        zinc = Zinc(settings)
        assert zinc.can_connect() is True

    def test_invalid_postgres_host(self, settings: ZincSettings):
        """Test that exception is raised if Postgres host does not exist."""
        settings.peers["postgres"].host = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert 'could not translate host name "foo" to address' in str(exc.value)

    def test_invalid_postgres_port(self, settings: ZincSettings):
        """Test that exception is raised if Postgres port does not exist."""
        settings.peers["postgres"].port = 404
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert re.search(r'connection to server at "postgres" .+ port 404 failed', str(exc.value))

    def test_invalid_postgres_username(self, settings: ZincSettings):
        """Test that exception is raised if Postgres authentication failed."""
        settings.peers["postgres"].username = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert "password authentication failed" in str(exc.value)

    def test_invalid_postgres_password(self, settings: ZincSettings):
        """Test that exception is raised if Postgres authentication failed."""
        settings.peers["postgres"].password = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert "password authentication failed" in str(exc.value)

    def test_invalid_postgres_database(self, settings: ZincSettings):
        """Test that exception is raised if Postgres database does not exist."""
        settings.peers["postgres"].database = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert 'database "foo" does not exist' in str(exc.value)


class TestMirrorBasicSettings:
    @pytest.fixture(scope="class")
    def settings(self) -> Generator[ZincSettings, Any, None]:
        with open("/app/tests/zinc/fixtures/basic_settings.yaml", "rt") as fp:
            settings = yaml.safe_load(fp)
        yield ZincSettings(**settings)

    @pytest.fixture(scope="class")
    def duckdb_adapter(self, settings: ZincSettings):
        yield DuckDBAdapter(settings.peers["duckdb"])

    @pytest.fixture(scope="class")
    def postgres_adapter(self, settings: ZincSettings):
        yield PostgresAdapter(settings.peers["postgres"])

    def test_postgres_to_duckdb(
        self,
        settings: ZincSettings,
        duckdb_adapter: DuckDBAdapter,
        postgres_adapter: PostgresAdapter,
    ):
        # Setup
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("""
            drop table if exists public.items;
            create table public.items (
                id integer,
                category_id varchar(1)
            );
            insert into public.items values
                (1, 'C'),
                (2, 'A'),
                (3, 'B'),
                (4, 'B'),
                (5, 'A');
            """)

        # Mirror tables
        Zinc(settings).mirror("postgres_to_duckdb")

        # Validate result
        with duckdb_adapter.create_client() as conn:
            actual = (
                conn.query("select id, category_id from test.main.items;")
                .to_df()
                .to_dict(orient="records")
            )
            expected = [
                {"id": 1, "category_id": "C"},
                {"id": 2, "category_id": "A"},
                {"id": 3, "category_id": "B"},
                {"id": 4, "category_id": "B"},
                {"id": 5, "category_id": "A"},
            ]
            assert_list_of_dicts_equal_ignore_order(actual, expected)

        # Teardown
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("drop table if exists public.items;")

        with duckdb_adapter.create_client() as conn:
            conn.execute("drop table if exists test.main.items;")

    def test_duckdb_to_postgres(
        self,
        settings: ZincSettings,
        duckdb_adapter: DuckDBAdapter,
        postgres_adapter: PostgresAdapter,
    ):
        # Setup
        with duckdb_adapter.create_client() as conn:
            conn.execute("""
            drop table if exists test.main.items;
            create table test.main.items (
                id integer,
                category_id varchar(1)
            );
            insert into test.main.items values
                (1, 'C'),
                (2, 'A'),
                (3, 'B'),
                (4, 'B'),
                (5, 'A');
            """)

        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("create schema if not exists duckdb;")

        # Mirror tables
        Zinc(settings).mirror("duckdb_to_postgres")

        # Validate result
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("select id, category_id from duckdb.items;")
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            actual = [dict(zip(columns, row)) for row in rows]
            expected = [
                {"id": 1, "category_id": "C"},
                {"id": 2, "category_id": "A"},
                {"id": 3, "category_id": "B"},
                {"id": 4, "category_id": "B"},
                {"id": 5, "category_id": "A"},
            ]
            assert_list_of_dicts_equal_ignore_order(actual, expected)

            cur.execute("""
            select lower(indexdef)
            from pg_indexes
            where schemaname = 'duckdb' and tablename = 'items';
            """)
            rows = cur.fetchall()
            assert rows == []

        # Teardown
        with duckdb_adapter.create_client() as conn:
            conn.execute("drop table if exists test.main.items;")

        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("drop schema if exists duckdb cascade;")


class TestMirrorAdvancedSettings:
    @pytest.fixture(scope="class")
    def settings(self) -> Generator[ZincSettings, Any, None]:
        with open("/app/tests/zinc/fixtures/advanced_settings.yaml", "rt") as fp:
            settings = yaml.safe_load(fp)
        yield ZincSettings(**settings)

    @pytest.fixture(scope="class")
    def duckdb_adapter(self, settings: ZincSettings):
        yield DuckDBAdapter(settings.peers["duckdb"])

    @pytest.fixture(scope="class")
    def postgres_adapter(self, settings: ZincSettings):
        yield PostgresAdapter(settings.peers["postgres"])

    def test_postgres_to_duckdb(
        self,
        settings: ZincSettings,
        duckdb_adapter: DuckDBAdapter,
        postgres_adapter: PostgresAdapter,
    ):
        # Setup
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("""
            drop table if exists public.items;
            create table public.items (
                id integer,
                category_id varchar(1)
            );
            insert into public.items values
                (1, 'C'),
                (2, 'A'),
                (3, 'B'),
                (4, 'B'),
                (5, 'A');
            """)

        # Mirror tables
        Zinc(settings).mirror("postgres_to_duckdb")

        # Validate result
        with duckdb_adapter.create_client() as conn:
            actual = (
                conn.query("select id, category_id from test.main.items;")
                .to_df()
                .to_dict(orient="records")
            )
            expected = [{"id": 2, "category_id": "A"}, {"id": 5, "category_id": "A"}]
            assert_list_of_dicts_equal_ignore_order(actual, expected)

        # Teardown
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("drop table if exists public.items;")

        with duckdb_adapter.create_client() as conn:
            conn.execute("drop table if exists test.main.items;")

    def test_duckdb_to_postgres(
        self,
        settings: ZincSettings,
        duckdb_adapter: DuckDBAdapter,
        postgres_adapter: PostgresAdapter,
    ):
        # Setup
        with duckdb_adapter.create_client() as conn:
            conn.execute("""
            drop table if exists test.main.items;
            create table test.main.items (
                id integer,
                category_id varchar(1)
            );
            insert into test.main.items values
                (1, 'C'),
                (2, 'A'),
                (3, 'B'),
                (4, 'B'),
                (5, 'A');
            """)

        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("create schema if not exists duckdb;")

        # Mirror tables
        Zinc(settings).mirror("duckdb_to_postgres")

        # Validate result
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("select id, category_id from duckdb.items;")
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            actual = [dict(zip(columns, row)) for row in rows]
            expected = [{"id": 2, "category_id": "A"}, {"id": 5, "category_id": "A"}]
            assert_list_of_dicts_equal_ignore_order(actual, expected)

            cur.execute("""
            select lower(indexdef)
            from pg_indexes
            where schemaname = 'duckdb' and tablename = 'items';
            """)
            rows = cur.fetchall()
            assert rows == [
                ("create index ix_items_category_id on duckdb.items using btree (category_id)",)
            ]

        # Teardown
        with duckdb_adapter.create_client() as conn:
            conn.execute("drop table if exists test.main.items;")

        with postgres_adapter.create_client() as (conn, cur):
            cur.execute("drop schema if exists duckdb cascade;")
