from ...asserts import assert_sql_equal
from clickhouse_sqlalchemy import engines, types
from dw_lib.utils.sqlmodel_utils import make_create_table_statement
from sqlalchemy import Column
from sqlglot.dialects.dialect import Dialects
from sqlmodel import Field, SQLModel

import pytest


class ModelWithoutSchema(SQLModel, table=True):
    __tablename__ = "table_without_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            index_granularity=8192,
        ),
    )


class ModelWithSchema(SQLModel, table=True):
    __tablename__ = "table_with_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            index_granularity=8192,
        ),
        {"schema": "analytics"},
    )


class TestModelWithoutSchema:
    @pytest.fixture
    def dialect(self):
        return Dialects.CLICKHOUSE

    @pytest.fixture
    def model(self):
        return ModelWithoutSchema

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


class TestModelWithSchema:
    @pytest.fixture
    def dialect(self):
        return Dialects.CLICKHOUSE

    @pytest.fixture
    def model(self):
        return ModelWithSchema

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
