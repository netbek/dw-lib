from ...asserts import assert_count_equal
from dw_lib import DuckDBAdapter, PostgresAdapter, Zinc, ZincSettings
from typing import Any, Generator

import os
import psycopg2
import pytest
import re
import yaml


class TestDuckDBSystemSettings:
    @pytest.fixture(scope="function")
    def settings_dict(self, pytestconfig) -> Generator[dict, Any, None]:
        with open(
            os.path.join(
                pytestconfig.rootpath, "tests/integration/zinc/fixtures/basic_settings.yaml"
            ),
            "rt",
        ) as fp:
            settings = yaml.safe_load(fp)
        yield settings

    def test_extra_settings(self, settings_dict: dict):
        """Test that extra settings are allowed."""
        settings_dict["peers"]["duckdb"]["settings"] = {"foo": "bar"}
        settings = ZincSettings(**settings_dict)
        assert settings.peers["duckdb"].settings.foo == "bar"

    def test_memory_limit_absolute_value(self, settings_dict: dict):
        """Test that memory limit as absolute value is preserved."""
        settings_dict["peers"]["duckdb"]["settings"] = {"memory_limit": "8GB"}
        settings = ZincSettings(**settings_dict)
        assert re.search(r"^\d+(\.\d+)?GB$", settings.peers["duckdb"].settings.memory_limit)

    def test_memory_limit_percentage_value(self, settings_dict: dict):
        """Test that memory limit as percentage value is converted to absolute value in GB."""
        settings_dict["peers"]["duckdb"]["settings"] = {"memory_limit": "50%"}
        settings = ZincSettings(**settings_dict)
        assert re.search(r"^\d+(\.\d+)?GB$", settings.peers["duckdb"].settings.memory_limit)

    def test_threads_absolute_value(self, settings_dict: dict):
        """Test that threads as absolute value is preserved."""
        settings_dict["peers"]["duckdb"]["settings"] = {"threads": 2}
        settings = ZincSettings(**settings_dict)
        assert isinstance(settings.peers["duckdb"].settings.threads, int)

    def test_threads_percentage_value(self, settings_dict: dict):
        """Test that threads as percentage value is converted to absolute value."""
        settings_dict["peers"]["duckdb"]["settings"] = {"threads": "50%"}
        settings = ZincSettings(**settings_dict)
        assert isinstance(settings.peers["duckdb"].settings.threads, int)


class TestCanConnect:
    @pytest.fixture(scope="function")
    def settings(self, pytestconfig) -> Generator[ZincSettings, Any, None]:
        with open(
            os.path.join(
                pytestconfig.rootpath, "tests/integration/zinc/fixtures/basic_settings.yaml"
            ),
            "rt",
        ) as fp:
            settings = yaml.safe_load(fp)
        yield ZincSettings(**settings)

    def test_valid_peers(self, postgres_adapter: PostgresAdapter, settings: ZincSettings):
        zinc = Zinc(settings)
        assert zinc.can_connect() is True

    def test_invalid_postgres_host(self, postgres_adapter: PostgresAdapter, settings: ZincSettings):
        """Test that exception is raised if Postgres host does not exist."""
        settings.peers["postgres"].host = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert 'could not translate host name "foo" to address' in str(exc.value)

    def test_invalid_postgres_port(self, postgres_adapter: PostgresAdapter, settings: ZincSettings):
        """Test that exception is raised if Postgres port does not exist."""
        settings.peers["postgres"].port = 404
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert re.search(r'connection to server at "localhost" .+ port 404 failed', str(exc.value))

    def test_invalid_postgres_username(
        self, postgres_adapter: PostgresAdapter, settings: ZincSettings
    ):
        """Test that exception is raised if Postgres authentication failed."""
        settings.peers["postgres"].username = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert "password authentication failed" in str(exc.value)

    def test_invalid_postgres_password(
        self, postgres_adapter: PostgresAdapter, settings: ZincSettings
    ):
        """Test that exception is raised if Postgres authentication failed."""
        settings.peers["postgres"].password = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert "password authentication failed" in str(exc.value)

    def test_invalid_postgres_database(
        self, postgres_adapter: PostgresAdapter, settings: ZincSettings
    ):
        """Test that exception is raised if Postgres database does not exist."""
        settings.peers["postgres"].database = "foo"
        zinc = Zinc(settings)

        with pytest.raises(Exception) as exc:
            zinc.can_connect()

        assert exc.type == psycopg2.OperationalError
        assert 'database "foo" does not exist' in str(exc.value)


class TestMirrorBasicSettings:
    @pytest.fixture(scope="class")
    def settings(self, pytestconfig) -> Generator[ZincSettings, Any, None]:
        with open(
            os.path.join(
                pytestconfig.rootpath, "tests/integration/zinc/fixtures/basic_settings.yaml"
            ),
            "rt",
        ) as fp:
            settings = yaml.safe_load(fp)
        yield ZincSettings(**settings)

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
            assert_count_equal(actual, expected)

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
            assert_count_equal(actual, expected)

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
    def settings(self, pytestconfig) -> Generator[ZincSettings, Any, None]:
        with open(
            os.path.join(
                pytestconfig.rootpath, "tests/integration/zinc/fixtures/advanced_settings.yaml"
            ),
            "rt",
        ) as fp:
            settings = yaml.safe_load(fp)
        yield ZincSettings(**settings)

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
            assert_count_equal(actual, expected)

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
            assert_count_equal(actual, expected)

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
