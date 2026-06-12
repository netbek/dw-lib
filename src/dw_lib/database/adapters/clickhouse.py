from ...exceptions import (
    DatabaseExistsException,
    DatabaseNotFoundException,
    TableExistsException,
    TableNotFoundException,
    UserExistsException,
    UserNotFoundException,
)
from ...types import ColumnStats, TableStats
from ..adapters.base import BaseAdapter
from ..types import ClickHouseRelation, ClickHouseSettings
from ..utils import quote_identifier
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import DatabaseError
from collections.abc import Generator
from contextlib import contextmanager
from sqlalchemy import inspect, MetaData, Table
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlglot.dialects.dialect import Dialects
from typing import Any, Literal

import clickhouse_connect


class ClickHouseAdapter(BaseAdapter[ClickHouseSettings]):
    dialect = Dialects.CLICKHOUSE
    settings_class = ClickHouseSettings

    @contextmanager
    def create_client(self) -> Generator[Client, Any, None]:
        client = clickhouse_connect.get_client(
            host=self.settings.host,
            port=self.settings.port,
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
            metadata = MetaData()
            inspector = inspect(engine)

            if not inspector.has_table(table, schema=database):
                raise TableNotFoundException(f"Table '{table}' not found")

            try:
                table_metadata = Table(table, metadata, schema=database, autoload_with=engine)
            except InvalidRequestError as exc:
                raise exc

        return table_metadata

    def get_table_stats(self, table: str, database: str | None = None) -> TableStats:
        table_metadata = self.get_table(table, database=database)

        measures = []
        for column in table_metadata.columns:
            name = column.name
            measures.append(f"coalesce(uniqCombined(`{name}`), 0) as `{name}_cardinality`")
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
            metadata = MetaData()
            inspector = inspect(engine)
            table_names = inspector.get_table_names(schema=database)
            view_names = inspector.get_view_names(schema=database)
            all_names = list(set(table_names + view_names))

            tables = []
            for name in all_names:
                try:
                    table = Table(name, metadata, schema=database, autoload_with=engine)
                    tables.append(table)
                except Exception:
                    continue

        return sorted(tables, key=lambda table: table.name)

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
