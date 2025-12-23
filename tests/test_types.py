from dw_lib.types import ClickHouseTableIdentifier, PostgresTableIdentifier
from pydantic_core import ValidationError

import pytest


class TestClickHouseTableIdentifier:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            ClickHouseTableIdentifier()

    def test_from_string_database_and_table(self):
        relation = ClickHouseTableIdentifier.from_string("my_database.my_table")
        assert relation.database == "my_database"
        assert relation.table == "my_table"

    def test_from_string_table(self):
        relation = ClickHouseTableIdentifier.from_string("my_table")
        assert relation.database is None
        assert relation.table == "my_table"

    def test_from_string_empty_string(self):
        with pytest.raises(ValueError):
            ClickHouseTableIdentifier.from_string("")

    def test_to_string_database_and_table(self):
        relation = ClickHouseTableIdentifier(database="my_database", table="my_table")
        assert str(relation) == "`my_database`.`my_table`"

    def test_to_string_table(self):
        relation = ClickHouseTableIdentifier(table="my_table")
        assert str(relation) == "`my_table`"


class TestPostgresTableIdentifier:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            PostgresTableIdentifier()

    def test_from_string_database_and_schema_and_table(self):
        relation = PostgresTableIdentifier.from_string("my_database.my_schema.my_table")
        assert relation.database == "my_database"
        assert relation.schema_ == "my_schema"
        assert relation.table == "my_table"

    def test_from_string_schema_and_table(self):
        relation = PostgresTableIdentifier.from_string("my_schema.my_table")
        assert relation.schema_ == "my_schema"
        assert relation.table == "my_table"

    def test_from_string_table(self):
        relation = PostgresTableIdentifier.from_string("my_table")
        assert relation.schema_ is None
        assert relation.table == "my_table"

    def test_from_string_empty_string(self):
        with pytest.raises(ValueError):
            PostgresTableIdentifier.from_string("")

    def test_to_string_database_and_schema_and_table(self):
        relation = PostgresTableIdentifier(
            database="my_database", schema_="my_schema", table="my_table"
        )
        assert str(relation) == '"my_database"."my_schema"."my_table"'

    def test_to_string_schema_and_table(self):
        relation = PostgresTableIdentifier(schema_="my_schema", table="my_table")
        assert str(relation) == '"my_schema"."my_table"'

    def test_to_string_table(self):
        relation = PostgresTableIdentifier(table="my_table")
        assert str(relation) == '"my_table"'
