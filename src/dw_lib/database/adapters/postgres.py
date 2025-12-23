from ...exceptions import (
    PublicationExistsException,
    PublicationNotFoundException,
    TableExistsException,
    TableNotFoundException,
    UserExistsException,
    UserNotFoundException,
)
from ...types import (
    CreateTableStatementOptions,
    PostgresIdentifier,
    PostgresRelation,
    PostgresSettings,
)
from ..adapters.base import BaseAdapter
from collections.abc import Generator
from contextlib import contextmanager
from sqlalchemy import URL
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.schema import CreateTable
from sqlglot.dialects.dialect import Dialects
from sqlmodel import Column, MetaData, Session, SQLModel, Table
from typing import Any, Literal

import psycopg2
import pydash


class PostgresAdapter(BaseAdapter):
    def __init__(self, settings: PostgresSettings) -> None:
        self.dialect = Dialects.POSTGRES
        super().__init__(settings)

    @classmethod
    def create_url(cls, host: str, port: int, username: str, password: str, database: str) -> URL:
        return URL.create(
            "postgresql",
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
            self.settings.port,
            self.settings.username,
            self.settings.password,
            self.settings.database,
        )

    @contextmanager
    def create_client(
        self, autocommit: bool = True
    ) -> Generator[tuple[psycopg2.extensions.connection, psycopg2.extensions.cursor], Any, None]:
        conn = psycopg2.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.username,
            password=self.settings.password,
            database=self.settings.database,
        )

        conn.autocommit = autocommit

        with conn.cursor() as cur:
            yield (conn, cur)

        cur.close()
        conn.close()

    @contextmanager
    def create_session(self) -> Generator[Session, Any, None]:
        with self.create_engine() as engine:
            session = Session(engine)

        yield session

        session.close()

    def can_connect(self) -> bool:
        with self.create_client() as (conn, cur):
            cur.execute("select 1;")
            result = cur.fetchone() == (1,)

        return result

    def has_database(self, database: str) -> bool:
        statement = """
        select 1 from information_schema.schemata
        where catalog_name = %(database)s
        limit 1;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"database": database})
            result = bool(cur.fetchall())

        return result

    def create_database(
        self, database: str, if_exists: Literal["fail", "replace"] = "fail"
    ) -> None:
        raise NotImplementedError()

    def drop_database(self, database: str, if_exists: bool | None = False) -> None:
        raise NotImplementedError()

    def has_schema(self, schema: str, database: str | None = None):
        if database is None:
            database = self.settings.database

        statement = """
        select 1 from information_schema.schemata
        where catalog_name = %(database)s
        and schema_name = %(schema)s
        limit 1;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"database": database, "schema": schema})
            result = bool(cur.fetchall())

        return result

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

    def has_table(self, table: str, database: str | None = None, schema: str | None = None) -> bool:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        statement = """
        select 1 from information_schema.tables
        where table_catalog = %(database)s
        and table_schema = %(schema)s
        and table_name = %(table)s;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"database": database, "schema": schema, "table": table})
            result = bool(cur.fetchall())

        return result

    def create_table(
        self,
        table: str,
        statement: str,
        database: str | None = None,
        schema: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if self.has_table(table=table, database=database, schema=schema):
            if if_exists == "replace":
                self.drop_table(table=table, database=database, schema=schema)
            else:
                raise TableExistsException(f"Table '{table}' exists")

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def make_create_table_statement_from_table(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
        options: CreateTableStatementOptions | None = None,
    ) -> str:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if not options:
            options = {}

        option_schema = options.get("schema", schema)
        option_if_not_exists = options.get("if_not_exists")
        option_include_autoincrement = options.get("include_autoincrement")
        option_include_index = options.get("include_index")
        option_include_primary_key_constraint = options.get("include_primary_key_constraint")
        option_include_foreign_key_constraint = options.get("include_foreign_key_constraint")
        option_include_unique_constraint = options.get("include_unique_constraint")

        url = self.create_url(
            **self.settings.model_copy(update={"database": database}).model_dump(
                by_alias=True, exclude=["schema_"]
            )
        )
        table_metadata = self.get_table(table, database=database, schema=schema)

        columns = [
            Column(
                name=column.name,
                type_=column.type,
                autoincrement=column.autoincrement if option_include_autoincrement else None,
                # default=column.default,
                index=column.index if option_include_index else None,
                unique=column.unique if option_include_unique_constraint else None,
                nullable=column.nullable,
                primary_key=column.primary_key if option_include_primary_key_constraint else None,
                server_default=column.server_default,
                # server_onupdate=column.server_onupdate,
            )
            for column in table_metadata.columns
        ]
        table_metadata = Table(table_metadata.name, MetaData(option_schema), *columns)

        with self.create_engine(url=url) as engine:
            kwargs = {"if_not_exists": option_if_not_exists}

            if not option_include_foreign_key_constraint:
                kwargs["include_foreign_key_constraints"] = []

            statement = str(CreateTable(table_metadata, **kwargs).compile(engine))

        return statement

    def make_create_table_statement_from_model(
        self,
        model: type[SQLModel],
        table: str | None = None,
        database: str | None = None,
        sql: str | None = None,
        pretty: bool = False,
        pad: int = 2,
        indent: int = 2,
    ) -> str:
        raise NotImplementedError()

    def make_create_view_statement_from_model(
        self,
        model: type[SQLModel],
        sql: str,
        table: str | None = None,
        database: str | None = None,
        pretty: bool = False,
        pad: int = 2,
        indent: int = 2,
    ) -> str:
        raise NotImplementedError()

    def drop_table(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
        if_exists: bool | None = False,
    ) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if not self.has_table(table=table, database=database, schema=schema):
            if if_exists:
                return
            else:
                raise TableNotFoundException(f"Table '{table}' not found")

        statement = (
            f"drop table {PostgresRelation(database=database, schema_=schema, table=table)};"
        )

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def truncate_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if not self.has_table(table=table, database=database, schema=schema):
            return

        statement = (
            f"truncate table {PostgresRelation(database=database, schema_=schema, table=table)};"
        )

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def get_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> Table:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        url = self.create_url(
            **self.settings.model_copy(update={"database": database}).model_dump(
                by_alias=True, exclude=["schema_"]
            )
        )

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=schema)

            try:
                metadata.reflect(bind=engine, views=True, only=[table])
                table_metadata = metadata.tables.get(f"{schema}.{table}")
            except InvalidRequestError as exc:
                if "requested table(s) not available" in str(exc):
                    raise TableNotFoundException()
                else:
                    raise exc

        return table_metadata

    def get_table_replica_identity(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if not self.has_table(table=table, database=database, schema=schema):
            return

        statement = """
        select
            case c.relreplident
                when 'd' then 'default'
                when 'n' then 'nothing'
                when 'f' then 'full'
                when 'i' then 'index'
            end as replica_identity
        from information_schema.tables as t
        join pg_class as c on c.oid = t.table_name::regclass
        where
            t.table_catalog = %(database)s
            and t.table_schema = %(schema)s
            and t.table_name = %(table)s;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"database": database, "schema": schema, "table": table})
            result = cur.fetchone()[0]

        return result

    def set_table_replica_identity(
        self,
        table: str,
        replica_identity: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if not self.has_table(table=table, database=database, schema=schema):
            return

        statement = f"alter table {PostgresRelation(database=database, schema_=schema, table=table)} replica identity {replica_identity};"

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def drop_tables(self, database: str | None = None, schema: str | None = None) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        for table in self.list_tables(database=database, schema=schema):
            self.drop_table(table.name, database=database, schema=schema)

    def list_tables(self, database: str | None = None, schema: str | None = None) -> list[Table]:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        url = self.create_url(
            **self.settings.model_copy(update={"database": database}).model_dump(
                by_alias=True, exclude=["schema_"]
            )
        )

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=schema)
            metadata.reflect(bind=engine, views=True)
            tables = pydash.sort_by(list(metadata.tables.values()), lambda table: table.name)

        return tables

    def has_user(self, username: str) -> bool:
        statement = """
        select 1
        from pg_catalog.pg_user
        where usename = %(username)s;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"username": username})
            result = bool(cur.fetchall())

        return result

    def create_user(
        self,
        username: str,
        password: str,
        options: dict | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None:
        if self.has_user(username):
            if if_exists == "replace":
                self.drop_user(username)
            else:
                raise UserExistsException(f"User '{username}' exists")

        quoted_username = PostgresIdentifier.quote(username)

        computed_options = []
        if options:
            if options.get("login"):
                computed_options.append("login")
            if options.get("replication"):
                computed_options.append("replication")

        statement = f"""
        create user {quoted_username}
        with {" ".join(computed_options)} password %(password)s;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"password": password})

    def drop_user(self, username: str, if_exists: bool | None = False) -> None:
        if not self.has_user(username):
            if if_exists:
                return
            else:
                raise UserNotFoundException(f"User '{username}' not found")

        quoted_username = PostgresIdentifier.quote(username)
        statement = f"""
        drop owned by {quoted_username} cascade;
        drop user {quoted_username};
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def grant_user_privileges(self, username: str, schema: str) -> None:
        if not self.has_user(username):
            raise Exception()

        quoted_username = PostgresIdentifier.quote(username)
        quoted_schema = PostgresIdentifier.quote(schema)
        statement = f"""
        grant usage on schema {quoted_schema} to {quoted_username};
        grant select on all tables in schema {quoted_schema} to {quoted_username};
        alter default privileges in schema {quoted_schema} grant select on tables to {quoted_username};
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def revoke_user_privileges(self, username: str, schema: str) -> None:
        if not self.has_user(username):
            return

        quoted_username = PostgresIdentifier.quote(username)
        quoted_schema = PostgresIdentifier.quote(schema)
        statement = f"""
        alter default privileges for user {quoted_username} in schema {quoted_schema} revoke select on tables from {quoted_username};
        revoke select on all tables in schema {quoted_schema} from {quoted_username};
        revoke usage on schema {quoted_schema} from {quoted_username};
        -- reassign owned by {quoted_username} to postgres;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def list_user_privileges(self, username: str) -> list[tuple] | None:
        if not self.has_user(username):
            return

        statement = """
        select
            table_catalog as database,
            table_schema as schema,
            table_name as table,
            privilege_type as privilege
        from information_schema.role_table_grants
        where grantee = %(username)s
        order by 1, 2, 3, 4;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"username": username})
            result = cur.fetchall()

        return result

    def has_publication(self, publication: str) -> bool:
        statement = "select 1 from pg_publication where pubname = %(publication)s;"

        with self.create_client() as (conn, cur):
            cur.execute(statement, {"publication": publication})
            result = bool(cur.fetchall())

        return result

    def create_publication(
        self, publication: str, tables: list[str], if_exists: Literal["fail", "replace"] = "fail"
    ) -> None:
        if self.has_publication(publication):
            if if_exists == "replace":
                self.drop_publication(publication)
            else:
                raise PublicationExistsException(f"Publication '{publication}' exists")

        quoted_publication = PostgresIdentifier.quote(publication)
        tables = [str(PostgresRelation.from_string(table)) for table in tables]
        statement = f"create publication {quoted_publication} for table {', '.join(tables)};"

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def drop_publication(self, publication: str, if_exists: bool | None = False) -> None:
        if not self.has_publication(publication):
            if if_exists:
                return
            else:
                raise PublicationNotFoundException(f"Publication '{publication}' not found")

        quoted_publication = PostgresIdentifier.quote(publication)
        statement = f"drop publication {quoted_publication};"

        with self.create_client() as (conn, cur):
            cur.execute(statement)

    def list_publications(self) -> list[str]:
        statement = """
        select pubname as publication
        from pg_catalog.pg_publication;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            result = [row[0] for row in cur.fetchall()]

        return result
