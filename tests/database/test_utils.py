from dw_lib.database import parse_create_table_statement, render_statement
from jinja2.exceptions import UndefinedError

import pytest


class TestParseCreateTableStatement:
    def test_no_properties(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": None,
            "version": None,
            "is_deleted": None,
            "primary_key": [],
            "order_by": [],
            "settings": {},
        }

        assert actual == expected

    def test_engine_version(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree(_peerdb_version)
        PRIMARY KEY id
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": "_peerdb_version",
            "is_deleted": None,
            "primary_key": ["id"],
            "order_by": [],
            "settings": {},
        }

        assert actual == expected

    def test_engine_version_and_is_deleted(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree(_peerdb_version, _peerdb_is_deleted)
        PRIMARY KEY id
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": "_peerdb_version",
            "is_deleted": "_peerdb_is_deleted",
            "primary_key": ["id"],
            "order_by": [],
            "settings": {},
        }

        assert actual == expected

    def test_primary_key_string(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree
        PRIMARY KEY id
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": None,
            "is_deleted": None,
            "primary_key": ["id"],
            "order_by": [],
            "settings": {},
        }

        assert actual == expected

    def test_primary_key_tuple(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree
        PRIMARY KEY (id, country)
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": None,
            "is_deleted": None,
            "primary_key": ["id", "country"],
            "order_by": [],
            "settings": {},
        }

        assert actual == expected

    def test_order_by_string(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree
        ORDER BY id
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": None,
            "is_deleted": None,
            "primary_key": [],
            "order_by": ["id"],
            "settings": {},
        }

        assert actual == expected

    def test_order_by_tuple(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            country String,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree
        ORDER BY (id, country)
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": None,
            "is_deleted": None,
            "primary_key": [],
            "order_by": ["id", "country"],
            "settings": {},
        }

        assert actual == expected

    def test_settings(self):
        statement = """
        CREATE TABLE test_table
        (
            id UInt64,
            updated_at DateTime default now(),
            _peerdb_synced_at DateTime64(9) DEFAULT now64(),
            _peerdb_is_deleted Int8,
            _peerdb_version Int64
        )
        ENGINE = ReplacingMergeTree
        SETTINGS allow_nullable_key = 1, index_granularity = 8192
        """
        actual = parse_create_table_statement(statement)
        del actual["columns"]  # TODO Remove
        expected = {
            "engine": "ReplacingMergeTree",
            "version": None,
            "is_deleted": None,
            "primary_key": [],
            "order_by": [],
            "settings": {"allow_nullable_key": "1", "index_granularity": "8192"},
        }

        assert actual == expected


class TestRenderStatement:
    def test_has_context(self):
        query = """
        SELECT {{ columns|join(', ') }}
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        actual = render_statement(query, context={"columns": ["p.name", "c.name"]})
        expected = """
        SELECT p.name, c.name
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """.strip()
        assert actual == expected

    def test_has_undefined_context(self):
        query = """
        SELECT {{ columns|join(', ') }}
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        with pytest.raises(UndefinedError):
            render_statement(query)

    def test_pretty(self):
        query = """
        SELECT *
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        actual = render_statement(query, pretty=False)
        expected = query.strip()
        assert actual == expected

        query = """
        SELECT *
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        actual = render_statement(query, pretty=True)
        expected = """
select *
from persons as p
join countries as c on c.id = p.country_id
""".strip()
        assert actual == expected
