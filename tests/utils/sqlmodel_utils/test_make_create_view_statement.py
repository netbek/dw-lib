from ...asserts import assert_sql_equal
from .fixtures import ViewWithoutSchema, ViewWithSchema
from dw_lib.utils.sqlmodel_utils import make_create_view_statement
from sqlglot.dialects.dialect import Dialects

import pytest


class TestViewWithoutSchema:
    @pytest.fixture
    def dialect(self):
        return Dialects.CLICKHOUSE

    @pytest.fixture
    def model(self):
        return ViewWithoutSchema

    def test_defaults(self, dialect, model):
        actual = make_create_view_statement(dialect, model, model.__sql__)
        expected = """
        CREATE VIEW view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_sql_cte(self, dialect, model):
        actual = make_create_view_statement(
            dialect, model, "WITH final AS (SELECT 42 AS id) SELECT * FROM final"
        )
        expected = """
        CREATE VIEW view_without_schema
        AS WITH final AS (SELECT 42 AS id) SELECT * FROM final
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, dialect, model):
        actual = make_create_view_statement(dialect, model, model.__sql__, table="my_view")
        expected = """
        CREATE VIEW my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, dialect, model):
        actual = make_create_view_statement(dialect, model, model.__sql__, schema="my_schema")
        expected = """
        CREATE VIEW my_schema.view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, dialect, model):
        actual = make_create_view_statement(
            dialect, model, model.__sql__, schema="my_schema", table="my_view"
        )
        expected = """
        CREATE VIEW my_schema.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)


class TestViewWithSchema:
    @pytest.fixture
    def dialect(self):
        return Dialects.CLICKHOUSE

    @pytest.fixture
    def model(self):
        return ViewWithSchema

    def test_defaults(self, dialect, model):
        actual = make_create_view_statement(dialect, model, model.__sql__)
        expected = """
        CREATE VIEW analytics.view_with_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, dialect, model):
        actual = make_create_view_statement(dialect, model, model.__sql__, table="my_view")
        expected = """
        CREATE VIEW analytics.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, dialect, model):
        actual = make_create_view_statement(dialect, model, model.__sql__, schema="my_schema")
        expected = """
        CREATE VIEW my_schema.view_with_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, dialect, model):
        actual = make_create_view_statement(
            dialect, model, model.__sql__, schema="my_schema", table="my_view"
        )
        expected = """
        CREATE VIEW my_schema.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)
