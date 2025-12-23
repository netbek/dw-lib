from dw_lib.types import ClickHouseRelation, PostgresRelation
from pydantic_core import ValidationError

import pytest


class TestClickHouseRelation:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            ClickHouseRelation()

    def test_from_string_database_and_table(self):
        relation = ClickHouseRelation.from_string("my_database.my_table")
        assert relation.database == "my_database"
        assert relation.table == "my_table"

    def test_from_string_table(self):
        relation = ClickHouseRelation.from_string("my_table")
        assert relation.database is None
        assert relation.table == "my_table"

    def test_from_string_empty_string(self):
        with pytest.raises(ValueError):
            ClickHouseRelation.from_string("")

    def test_to_string_database_and_table(self):
        relation = ClickHouseRelation(database="my_database", table="my_table")
        assert str(relation) == "`my_database`.`my_table`"

    def test_to_string_table(self):
        relation = ClickHouseRelation(table="my_table")
        assert str(relation) == "`my_table`"


class TestPostgresRelation:
    def test_init_without_table(self):
        with pytest.raises(ValidationError):
            PostgresRelation()

    def test_from_string_database_and_schema_and_table(self):
        relation = PostgresRelation.from_string("my_database.my_schema.my_table")
        assert relation.database == "my_database"
        assert relation.schema_ == "my_schema"
        assert relation.table == "my_table"

    def test_from_string_schema_and_table(self):
        relation = PostgresRelation.from_string("my_schema.my_table")
        assert relation.schema_ == "my_schema"
        assert relation.table == "my_table"

    def test_from_string_table(self):
        relation = PostgresRelation.from_string("my_table")
        assert relation.schema_ is None
        assert relation.table == "my_table"

    def test_from_string_empty_string(self):
        with pytest.raises(ValueError):
            PostgresRelation.from_string("")

    def test_to_string_database_and_schema_and_table(self):
        relation = PostgresRelation(database="my_database", schema_="my_schema", table="my_table")
        assert str(relation) == '"my_database"."my_schema"."my_table"'

    def test_to_string_schema_and_table(self):
        relation = PostgresRelation(schema_="my_schema", table="my_table")
        assert str(relation) == '"my_schema"."my_table"'

    def test_to_string_table(self):
        relation = PostgresRelation(table="my_table")
        assert str(relation) == '"my_table"'
