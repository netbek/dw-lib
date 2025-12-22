from ...exceptions import (
    DatabaseExistsException,
    DatabaseNotFoundException,
    TableExistsException,
    TableNotFoundException,
    UserExistsException,
    UserNotFoundException,
)
from ...types import ClickHouseIdentifier, ClickHouseSettings, ClickHouseTableIdentifier
from ..adapters.base import BaseAdapter
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import DatabaseError
from collections.abc import Generator
from contextlib import contextmanager
from sqlalchemy import URL
from sqlalchemy.exc import InvalidRequestError
from sqlglot.dialects.dialect import Dialects
from sqlmodel import MetaData, Session, Table
from typing import Any, Literal

import clickhouse_connect
import pydash


class ClickHouseAdapter(BaseAdapter):
    def __init__(self, settings: ClickHouseSettings) -> None:
        self.dialect = Dialects.CLICKHOUSE
        super().__init__(settings)

    @classmethod
    def create_url(
        cls,
        host: str,
        http_port: int,
        tcp_port: int,
        username: str,
        password: str,
        database: str,
        driver: str | None = None,
        secure: bool | None = None,
    ) -> URL:
        if driver:
            scheme = f"clickhouse+{driver}"
        else:
            scheme = "clickhouse"

        if driver == "native":
            port = tcp_port
        else:
            port = http_port

        return URL.create(
            scheme,
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
        )

    @property
    def url(self) -> URL:
        return self.create_url(
            self.settings.host,
            self.settings.http_port,
            self.settings.tcp_port,
            self.settings.username,
            self.settings.password,
            self.settings.database,
            self.settings.driver,
            self.settings.secure,
        )

    @contextmanager
    def create_client(self) -> Generator[Client | None]:
        if self.settings.driver == "native":
            port = self.settings.tcp_port
        else:
            port = self.settings.http_port

        client = clickhouse_connect.get_client(
            host=self.settings.host,
            port=port,
            username=self.settings.username,
            password=self.settings.password,
            database=self.settings.database,
            secure=self.settings.secure,
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
        with self.create_client() as client:
            result = client.query("select 1;").first_row == (1,)

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
    ) -> None:
        if database is None:
            database = self.settings.database

        statement = "show create table {database:Identifier}.{table:Identifier};"

        with self.create_client() as client:
            try:
                statement = client.command(
                    statement, parameters={"database": database, "table": table}
                )
                statement = statement.replace("\\n", "\n")
            except DatabaseError as exc:
                if f"Table `{table}` doesn't exist" in str(exc):
                    raise TableNotFoundException()
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

        statement = f"drop table {ClickHouseTableIdentifier(database=database, table=table)};"

        with self.create_client() as client:
            client.command(statement)

    def truncate_table(self, table: str, database: str | None = None) -> None:
        if database is None:
            database = self.settings.database

        if not self.has_table(table=table, database=database):
            return

        statement = f"truncate table {ClickHouseTableIdentifier(database=database, table=table)};"

        with self.create_client() as client:
            client.command(statement)

    def get_table(self, table: str, database: str | None = None) -> Table:
        if database is None:
            database = self.settings.database

        url = self.create_url(**self.settings.model_dump())

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=database)

            try:
                metadata.reflect(bind=engine, views=True, only=[table])
                table_metadata = metadata.tables.get(f"{database}.{table}")
            except InvalidRequestError as exc:
                if "requested table(s) not available" in str(exc):
                    raise TableNotFoundException()
                else:
                    raise exc

        return table_metadata

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

        url = self.create_url(**self.settings.model_dump())

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=database)
            metadata.reflect(bind=engine, views=True)
            tables = pydash.sort_by(list(metadata.tables.values()), lambda table: table.name)

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

        quoted_username = ClickHouseIdentifier.quote(username)
        statement = f"create user {quoted_username} identified by %(password)s;"

        with self.create_client() as client:
            client.command(statement, parameters={"password": password})

    def drop_user(self, username: str, if_exists: bool | None = False) -> None:
        if not self.has_user(username):
            if if_exists:
                return
            else:
                raise UserNotFoundException(f"User '{username}' not found")

        quoted_username = ClickHouseIdentifier.quote(username)
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
