from clickhouse_sqlalchemy import engines, types
from dw_lib.utils.sqlmodel_utils import get_model_schema
from sqlalchemy import Column
from sqlglot.dialects.dialect import Dialects
from sqlmodel import Field, SQLModel

import pytest


class TableWithoutSchema(SQLModel, table=True):
    __tablename__ = "table_without_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            index_granularity=8192,
        ),
    )


class TableWithSchema(SQLModel, table=True):
    __tablename__ = "table_with_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            index_granularity=8192,
        ),
        {"schema": "analytics"},
    )


class ViewWithoutSchema(SQLModel):
    __tablename__ = "view_without_schema"
    __sql__ = """
    SELECT 42 AS id
    """


class ViewWithSchema(SQLModel):
    __tablename__ = "view_with_schema"
    __sql__ = """
    SELECT 42 AS id
    """
    __table_args__ = {"schema": "analytics"}


class TestGetModelSchema:
    def test_table_without_schema(self):
        assert get_model_schema(TableWithoutSchema) is None

    def test_table_with_schema(self):
        assert get_model_schema(TableWithSchema) == "analytics"

    def test_view_without_schema(self):
        assert get_model_schema(ViewWithoutSchema) is None

    def test_view_with_schema(self):
        assert get_model_schema(ViewWithSchema) == "analytics"
