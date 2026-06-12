from clickhouse_connect.cc_sqlalchemy import engines, types
from sqlalchemy import Column
from sqlmodel import Field, SQLModel


class TableWithoutSchema(SQLModel, table=True):
    __tablename__ = "table_without_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            settings={"index_granularity": 8192},
        ),
    )


class TableWithSchema(SQLModel, table=True):
    __tablename__ = "table_with_schema"

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __table_args__ = (
        engines.MergeTree(
            order_by=("id"),
            settings={"index_granularity": 8192},
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
