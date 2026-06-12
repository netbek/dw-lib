from ...asserts import assert_sql_equal
from ...conftest import DatabaseTest
from .conftest import ViewWithoutSchema, ViewWithSchema
from dw_lib.database import ClickHouseAdapter
from dw_lib.utils.sqlmodel_utils import make_create_view_statement_from_model

import pytest


class TestViewWithoutSchema(DatabaseTest):
    @pytest.fixture(scope="function")
    def model(self):
        return ViewWithoutSchema

    def test_defaults(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__)
        expected = """
        CREATE VIEW view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_if_not_exists(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__, if_not_exists=True)
        expected = """
        CREATE VIEW IF NOT EXISTS view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_replace(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__, replace=True)
        expected = """
        CREATE OR REPLACE VIEW view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_if_not_exists_and_replace(self, clickhouse_adapter: ClickHouseAdapter, model):
        with pytest.raises(ValueError):
            make_create_view_statement_from_model(
                model, model.__sql__, if_not_exists=True, replace=True
            )

    def test_sql_cte(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(
            model, "WITH final AS (SELECT 42 AS id) SELECT * FROM final"
        )
        expected = """
        CREATE VIEW view_without_schema
        AS WITH final AS (SELECT 42 AS id) SELECT * FROM final
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__, table="my_view")
        expected = """
        CREATE VIEW my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__, database="my_database")
        expected = """
        CREATE VIEW my_database.view_without_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(
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
        actual = make_create_view_statement_from_model(model, model.__sql__)
        expected = """
        CREATE VIEW analytics.view_with_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__, table="my_view")
        expected = """
        CREATE VIEW analytics.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(model, model.__sql__, database="my_database")
        expected = """
        CREATE VIEW my_database.view_with_schema
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)

    def test_override_schema_and_table(self, clickhouse_adapter: ClickHouseAdapter, model):
        actual = make_create_view_statement_from_model(
            model, model.__sql__, database="my_database", table="my_view"
        )
        expected = """
        CREATE VIEW my_database.my_view
        AS SELECT 42 AS id
        """
        assert_sql_equal(actual, expected)
