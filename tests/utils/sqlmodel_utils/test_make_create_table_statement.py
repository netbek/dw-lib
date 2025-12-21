from ...asserts import assert_sql_equal
from .fixtures import TableWithoutSchema, TableWithSchema
from dw_lib.utils.sqlmodel_utils import make_create_table_statement
from sqlglot.dialects.dialect import Dialects

import pytest


class TestTableWithoutSchema:
    @pytest.fixture
    def dialect(self):
        return Dialects.CLICKHOUSE

    @pytest.fixture
    def model(self):
        return TableWithoutSchema

    def test_defaults(self, dialect, model):
        actual = make_create_table_statement(dialect, model)
        expected = """
        CREATE TABLE table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_sql_query(self, dialect, model):
        actual = make_create_table_statement(dialect, model, sql="SELECT 42 AS id")
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

    def test_sql_cte(self, dialect, model):
        actual = make_create_table_statement(
            dialect, model, sql="WITH final AS (SELECT 42 AS id) SELECT * FROM final"
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

    def test_override_table(self, dialect, model):
        actual = make_create_table_statement(dialect, model, table="my_table")
        expected = """
        CREATE TABLE my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, dialect, model):
        actual = make_create_table_statement(dialect, model, schema="my_schema")
        expected = """
        CREATE TABLE my_schema.table_without_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, dialect, model):
        actual = make_create_table_statement(dialect, model, schema="my_schema", table="my_table")
        expected = """
        CREATE TABLE my_schema.my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)


class TestTableWithSchema:
    @pytest.fixture
    def dialect(self):
        return Dialects.CLICKHOUSE

    @pytest.fixture
    def model(self):
        return TableWithSchema

    def test_defaults(self, dialect, model):
        actual = make_create_table_statement(dialect, model)
        expected = """
        CREATE TABLE analytics.table_with_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, dialect, model):
        actual = make_create_table_statement(dialect, model, table="my_table")
        expected = """
        CREATE TABLE analytics.my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, dialect, model):
        actual = make_create_table_statement(dialect, model, schema="my_schema")
        expected = """
        CREATE TABLE my_schema.table_with_schema (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, dialect, model):
        actual = make_create_table_statement(dialect, model, schema="my_schema", table="my_table")
        expected = """
        CREATE TABLE my_schema.my_table (
            id Int32
        )
        ENGINE=MergeTree()
        ORDER BY id
        SETTINGS index_granularity = 8192
        """
        assert_sql_equal(actual, expected)
