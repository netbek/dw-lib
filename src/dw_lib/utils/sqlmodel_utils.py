from clickhouse_connect.cc_sqlalchemy.dialect import ClickHouseDialect
from dw_lib.exceptions import TableExpressionNotFoundException
from sqlalchemy import Table
from sqlalchemy.sql.ddl import CreateTable
from sqlglot import exp
from sqlglot.dialects.dialect import Dialects
from sqlmodel import SQLModel

import sqlglot


def get_model_schema(model: type[SQLModel]) -> str | None:
    table = getattr(model, "__table__", None)

    if isinstance(table, Table):
        return table.schema

    table_args = getattr(model, "__table_args__", None)

    if isinstance(table_args, dict):
        return table_args.get("schema")

    return None


def make_create_table_statement_from_model(
    model: type[SQLModel],
    table: str | None = None,
    database: str | None = None,
    sql: str | None = None,
    if_not_exists: bool | None = False,
    replace: bool | None = False,
    pretty: bool = False,
    pad: int = 2,
    indent: int = 2,
) -> str:
    if if_not_exists and replace:
        raise ValueError("if_not_exists and replace are mutually exclusive")

    statement = CreateTable(model.__table__, if_not_exists=if_not_exists).compile(
        dialect=ClickHouseDialect()
    )
    statement = str(statement)
    tree = sqlglot.parse_one(statement, read=Dialects.CLICKHOUSE)

    if replace:
        tree.set("replace", True)

    if table is not None or database is not None:
        table_exp = tree.find(exp.Table)

        if table_exp is None:
            raise TableExpressionNotFoundException("Table expression not found")

        if table is not None:
            table_exp.set("this", exp.Identifier(this=table))

        if database is not None:
            table_exp.set("db", exp.Identifier(this=database))

    if sql is not None:
        query_exp = sqlglot.parse_one(sql, read=Dialects.CLICKHOUSE)
        tree.set("expression", query_exp)

    return tree.sql(dialect=Dialects.CLICKHOUSE, pretty=pretty, pad=pad, indent=indent)


def make_create_view_statement_from_model(
    model: type[SQLModel],
    sql: str,
    table: str | None = None,
    database: str | None = None,
    if_not_exists: bool | None = False,
    replace: bool | None = False,
    pretty: bool = False,
    pad: int = 2,
    indent: int = 2,
) -> str:
    if if_not_exists and replace:
        raise ValueError("if_not_exists and replace are mutually exclusive")

    resolved_table = table or model.__tablename__
    resolved_database = database or get_model_schema(model)

    table_exp = exp.Table(
        this=exp.Identifier(this=resolved_table),
        db=exp.Identifier(this=resolved_database) if resolved_database else None,
    )
    query_exp = sqlglot.parse_one(sql, read=Dialects.CLICKHOUSE)
    tree = exp.Create(
        this=table_exp, kind="VIEW", expression=query_exp, exists=if_not_exists, replace=replace
    )

    return tree.sql(dialect=Dialects.CLICKHOUSE, pretty=pretty, pad=pad, indent=indent)
