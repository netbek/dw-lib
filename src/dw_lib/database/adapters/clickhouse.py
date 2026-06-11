from ...exceptions import (
    DatabaseExistsException,
    DatabaseNotFoundException,
    TableExistsException,
    TableNotFoundException,
    UserExistsException,
    UserNotFoundException,
)
from ...types import ColumnStats, TableStats
from ...utils.sqlmodel_utils import get_model_schema
from ..adapters.base import BaseAdapter
from ..types import ClickHouseRelation, ClickHouseSettings
from ..utils import quote_identifier
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import DatabaseError
from clickhouse_sqlalchemy.drivers.base import ClickHouseDialect
from collections.abc import Generator
from contextlib import contextmanager
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.sql.ddl import CreateTable
from sqlglot import exp
from sqlglot.dialects.dialect import Dialects
from sqlmodel import MetaData, Session, SQLModel, Table
from typing import Any, Literal

import clickhouse_connect
import sqlglot


class ClickHouseAdapter(BaseAdapter[ClickHouseSettings]):
    dialect = Dialects.CLICKHOUSE
    settings_class = ClickHouseSettings

    @contextmanager
    def create_client(self) -> Generator[Client, Any, None]:
        if self.settings.driver == "native":
            port = self.settings.tcp_port
        else:
            port = self.settings.http_port

        client = clickhouse_connect.get_client(
            host=self.settings.host,
            port=port or 0,
            username=self.settings.username,
            password=self.settings.password,
            database=self.settings.database,
        )

        yield client

        client.close()

    @contextmanager
    def create_session(self) -> Generator[Session, Any, None]:
        with self.create_engine() as engine:
            session = Session(engine)

        yield session

        session.close()

    def can_connect(self) -> bool:
        try:
            with self.create_client() as client:
                result = client.query("select 1;").first_row == (1,)
        except Exception:
            result = False

        return result

    def has_database(self, database: str) -> bool:
        statement = "select 1 from system.databases where name = {database:String};"

        with self.create_client() as client:
            result = bool(client.query(statement, parameters={"database": database}).result_rows)

        return result

    def create_database(
        self, database: str, if_exists: Literal["fail", "replace"] = "fail"
    ) -> None:
        if self.has_database(database):
            if if_exists == "replace":
                self.drop_database(database)
            else:
                raise DatabaseExistsException(f"Database '{database}' exists")

        statement = "create database {database:Identifier};"

        with self.create_client() as client:
            client.command(statement, parameters={"database": database})

    def drop_database(self, database: str, if_exists: bool | None = False) -> None:
        if not self.has_database(database):
            if if_exists:
                return
            else:
                raise DatabaseNotFoundException(f"Database '{database}' not found")

        statement = "drop database {database:Identifier};"

        with self.create_client() as client:
            client.command(statement, parameters={"database": database})

    def has_schema(self, schema: str, database: str | None = None) -> bool:
        raise NotImplementedError()

    def create_schema(
        self,
        schema: str,
        database: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None:
        raise NotImplementedError()

    def drop_schema(
        self, schema: str, database: str | None = None, if_exists: bool | None = False
    ) -> None:
        raise NotImplementedError()

    def has_table(self, table: str, database: str | None = None) -> bool:
        if database is None:
            database = self.settings.database

        statement = "select 1 from system.tables where database = {database:String} and name = {table:String};"

        with self.create_client() as client:
            result = bool(
                client.query(
                    statement, parameters={"database": database, "table": table}
                ).result_rows
            )

        return result

    def create_table(
        self,
        table: str,
        statement: str,
        database: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None:
        if database is None:
            database = self.settings.database

        if self.has_table(table=table, database=database):
            if if_exists == "replace":
                self.drop_table(table=table, database=database)
            else:
                raise TableExistsException(f"Table '{table}' exists")

        with self.create_client() as client:
            client.command(statement)

    def make_create_table_statement_from_table(
        self, table: str, database: str | None = None
    ) -> str:
        if database is None:
            database = self.settings.database

        statement = "show create table {database:Identifier}.{table:Identifier};"

        with self.create_client() as client:
            try:
                statement = client.command(
                    statement, parameters={"database": database, "table": table}
                )
                statement = str(statement).replace("\\n", "\n")
            except DatabaseError as exc:
                if f"Table `{table}` doesn't exist" in str(exc):
                    raise TableNotFoundException(f"Table '{table}' not found")
                else:
                    raise exc

        return statement

    def make_create_table_statement_from_model(
        self,
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
        tree = sqlglot.parse_one(statement, read=self.dialect)

        if replace:
            tree.set("replace", True)

        if table is not None or database is not None:
            table_exp = tree.find(exp.Table)

            if table_exp is None:
                raise Exception("Table expression not found")

            if table is not None:
                table_exp.set("this", exp.Identifier(this=table))

            if database is not None:
                table_exp.set("db", exp.Identifier(this=database))

        if sql is not None:
            query_exp = sqlglot.parse_one(sql, read=self.dialect)
            tree.set("expression", query_exp)

        return tree.sql(dialect=self.dialect, pretty=pretty, pad=pad, indent=indent)

    def make_create_view_statement_from_sqlmodel_model(
        self,
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
        query_exp = sqlglot.parse_one(sql, read=self.dialect)
        tree = exp.Create(
            this=table_exp, kind="VIEW", expression=query_exp, exists=if_not_exists, replace=replace
        )

        return tree.sql(dialect=self.dialect, pretty=pretty, pad=pad, indent=indent)

    def drop_table(
        self, table: str, database: str | None = None, if_exists: bool | None = False
    ) -> None:
        if database is None:
            database = self.settings.database

        if not self.has_table(table=table, database=database):
            if if_exists:
                return
            else:
                raise TableNotFoundException(f"Table '{table}' not found")

        statement = f"drop table {ClickHouseRelation(database=database, table=table)};"

        with self.create_client() as client:
            client.command(statement)

    def truncate_table(self, table: str, database: str | None = None) -> None:
        if database is None:
            database = self.settings.database

        if not self.has_table(table=table, database=database):
            return

        statement = f"truncate table {ClickHouseRelation(database=database, table=table)};"

        with self.create_client() as client:
            client.command(statement)

    def get_table(self, table: str, database: str | None = None) -> Table:
        if database is None:
            database = self.settings.database

        url = self.settings.to_sqlalchemy_url()

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=database)

            try:
                metadata.reflect(bind=engine, views=True, only=[table])
                table_metadata = metadata.tables[f"{database}.{table}"]
            except InvalidRequestError as exc:
                if "requested table(s) not available" in str(exc):
                    raise TableNotFoundException(f"Table '{table}' not found")
                else:
                    raise exc

        return table_metadata

    def get_table_stats(self, table: str, database: str | None = None) -> TableStats:
        table_metadata = self.get_table(table, database=database)

        measures = []
        for column in table_metadata.columns:
            name = column.name
            measures.append(f"uniqCombined(`{name}`) as `{name}_cardinality`")
            measures.append(f"countIf(isNull(`{name}`)) as `{name}_null_count`")
            measures.append(f"count(*) as `{name}_count`")

        query = f"select {', '.join(measures)} from {ClickHouseRelation(database=database, table=table)}"

        with self.create_client() as client:
            row = client.query(query).result_rows[0]

        column_stats = []
        for i, column in enumerate(table_metadata.columns):
            idx = i * 3
            cardinality = row[idx]
            null_count = row[idx + 1]
            count = row[idx + 2]
            null_pct = (null_count / count * 100) if count > 0 else 0
            column_stats.append(
                ColumnStats(
                    name=column.name,
                    data_type=str(column.type),
                    nullable=column.nullable,
                    cardinality=cardinality,
                    null_count=null_count,
                    null_pct=round(null_pct, 2),
                )
            )

        return TableStats(columns=column_stats)

    def get_table_replica_identity(self, table: str, database: str | None = None) -> None:
        raise NotImplementedError()

    def set_table_replica_identity(
        self, table: str, replica_identity: str, database: str | None = None
    ) -> None:
        raise NotImplementedError()

    def drop_tables(self, database: str | None = None) -> None:
        if database is None:
            database = self.settings.database

        for table in self.list_tables(database=database):
            self.drop_table(table.name, database=database)

    def list_tables(self, database: str | None = None) -> list[Table]:
        if database is None:
            database = self.settings.database

        url = self.settings.to_sqlalchemy_url()

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=database)
            metadata.reflect(bind=engine, views=True)
            tables = sorted(metadata.tables.values(), key=lambda table: table.name)

        return tables

    def has_user(self, username: str) -> bool:
        statement = "select 1 from system.users where name = {username:String};"

        with self.create_client() as client:
            result = bool(client.query(statement, parameters={"username": username}).result_rows)

        return result

    def create_user(
        self, username: str, password: str, if_exists: Literal["fail", "replace"] = "fail"
    ) -> None:
        if self.has_user(username):
            if if_exists == "replace":
                self.drop_user(username)
            else:
                raise UserExistsException(f"User '{username}' exists")

        quoted_username = quote_identifier(username, dialect=self.dialect)
        statement = f"create user {quoted_username} identified by %(password)s;"

        with self.create_client() as client:
            client.command(statement, parameters={"password": password})

    def drop_user(self, username: str, if_exists: bool | None = False) -> None:
        if not self.has_user(username):
            if if_exists:
                return
            else:
                raise UserNotFoundException(f"User '{username}' not found")

        quoted_username = quote_identifier(username, dialect=self.dialect)
        statement = f"drop user {quoted_username};"

        with self.create_client() as client:
            client.command(statement, parameters={"username": username})

    def grant_user_privileges(self, username: str, database: str) -> None:
        raise NotImplementedError()

    def revoke_user_privileges(self, username: str, database: str) -> None:
        raise NotImplementedError()

    def list_user_privileges(self, username: str) -> list[tuple]:
        raise NotImplementedError()

    def has_publication(self, publication: str) -> bool:
        raise NotImplementedError()

    def create_publication(
        self, publication: str, tables: list[str], if_exists: Literal["fail", "replace"] = "fail"
    ) -> None:
        raise NotImplementedError()

    def drop_publication(self, publication: str, if_exists: bool | None = False) -> None:
        raise NotImplementedError()

    def list_publications(self) -> list[str]:
        raise NotImplementedError()
