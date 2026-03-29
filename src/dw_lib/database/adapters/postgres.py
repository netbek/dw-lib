from ...exceptions import (
    PublicationExistsException,
    PublicationNotFoundException,
    TableExistsException,
    TableNotFoundException,
    UserExistsException,
    UserNotFoundException,
)
from ...types import PostgresRelation, PostgresSettings, TableStats
from ..adapters.base import BaseAdapter
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql.schema import ForeignKeyConstraint
from sqlglot.dialects.dialect import Dialects
from sqlmodel import Column, MetaData, Session, SQLModel, Table
from typing import Any, Literal


class PostgresAdapter(BaseAdapter[PostgresSettings]):
    dialect = Dialects.POSTGRES
    settings_class = PostgresSettings

    @contextmanager
    def create_client(self, autocommit: bool = False, row_factory: Any = None):
        """
        Creates and yields a PostgreSQL connection and cursor.

        Args:
            autocommit (bool, optional): If True, database operations are committed immediately. Defaults to False.
            row_factory (Any, optional): The strategy used to shape the resulting rows. Pass `psycopg.rows.dict_row` for psycopg 3 or `psycopg2.extras.RealDictCursor` for psycopg2. Defaults to None.

        Yields:
            tuple: A tuple containing (connection, cursor).
        """
        if self.settings.driver == "psycopg":
            import psycopg

            conn = psycopg.connect(
                host=self.settings.host,
                port=self.settings.port,
                user=self.settings.username,
                password=self.settings.password,
                dbname=self.settings.database,
                autocommit=autocommit,
            )

            with conn.cursor(row_factory=row_factory) as cur:
                yield (conn, cur)
        else:
            import psycopg2

            conn = psycopg2.connect(
                host=self.settings.host,
                port=self.settings.port,
                user=self.settings.username,
                password=self.settings.password,
                dbname=self.settings.database,
            )
            conn.autocommit = autocommit

            with conn.cursor(cursor_factory=row_factory) as cur:
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
        try:
            with self.create_client() as (conn, cur):
                cur.execute("select 1;")
                result = cur.fetchone() == (1,)
        except Exception:
            result = False

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
            conn.commit()

    def make_create_table_statement_from_table(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
        if_not_exists: bool | None = False,
        include_autoincrement: bool | None = False,
        include_index: bool | None = False,
        include_primary_key_constraint: bool | None = False,
        include_foreign_key_constraints: Sequence[ForeignKeyConstraint] | None = None,
        include_unique_constraint: bool | None = False,
    ) -> str:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        url = self.settings.model_copy(update={"database": database}).to_sqlalchemy_url()
        table_metadata = self.get_table(table, database=database, schema=schema)

        columns = []
        for column in table_metadata.columns:
            kwargs = {}
            if include_autoincrement:
                kwargs["autoincrement"] = column.autoincrement
            if include_index:
                kwargs["index"] = column.index
            if include_primary_key_constraint:
                kwargs["primary_key"] = column.primary_key
            if include_unique_constraint:
                kwargs["unique"] = column.unique

            columns.append(
                Column(
                    name=column.name,
                    type_=column.type,
                    # default=column.default,
                    nullable=column.nullable,
                    server_default=column.server_default,
                    # server_onupdate=column.server_onupdate,
                    **kwargs,
                )
            )
        table_metadata = Table(table_metadata.name, MetaData(schema), *columns)

        with self.create_engine(url=url) as engine:
            kwargs = {"if_not_exists": if_not_exists}

            if not include_foreign_key_constraints:
                kwargs["include_foreign_key_constraints"] = []

            statement = str(CreateTable(table_metadata, **kwargs).compile(engine))

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
        raise NotImplementedError()

    def make_create_view_statement_from_model(
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

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        statement = sql.SQL("drop table {table};").format(
            table=sql.Identifier(database, schema, table)
        )

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def truncate_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> None:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        if not self.has_table(table=table, database=database, schema=schema):
            return

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        statement = sql.SQL("truncate table {table};").format(
            table=sql.Identifier(database, schema, table)
        )

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def get_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> Table:
        if database is None:
            database = self.settings.database

        if schema is None:
            schema = self.settings.schema_

        url = self.settings.model_copy(update={"database": database}).to_sqlalchemy_url()

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=schema)

            try:
                metadata.reflect(bind=engine, views=True, only=[table])
                table_metadata = metadata.tables[f"{schema}.{table}"]
            except InvalidRequestError as exc:
                if "requested table(s) not available" in str(exc):
                    raise TableNotFoundException(f"Table '{table}' not found")
                else:
                    raise exc

        return table_metadata

    def get_table_stats(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> TableStats:
        raise NotImplementedError()

    def get_table_replica_identity(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> str | None:
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
            result = cur.fetchone()

        if not result:
            return None

        return result[0]

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

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        statement = sql.SQL("alter table {table} replica identity {replica_identity};").format(
            table=sql.Identifier(database, schema, table),
            replica_identity=sql.SQL(replica_identity),
        )

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

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

        url = self.settings.model_copy(update={"database": database}).to_sqlalchemy_url()

        with self.create_engine(url=url) as engine:
            metadata = MetaData(schema=schema)
            metadata.reflect(bind=engine, views=True)
            tables = sorted(metadata.tables.values(), key=lambda table: table.name)

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

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        computed_options = []
        if options:
            if options.get("login"):
                computed_options.append(sql.SQL("login"))
            if options.get("replication"):
                computed_options.append(sql.SQL("replication"))

        statement = sql.SQL("create user {username} with {options} password {password}").format(
            username=sql.Identifier(username),
            options=sql.SQL(" ").join(computed_options),
            password=sql.Literal(password),
        )

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def drop_user(self, username: str, if_exists: bool | None = False) -> None:
        if not self.has_user(username):
            if if_exists:
                return
            else:
                raise UserNotFoundException(f"User '{username}' not found")

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        statement = sql.SQL("""
        drop owned by {username} cascade;
        drop user {username};
        """).format(username=sql.Identifier(username))

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def grant_user_privileges(self, username: str, schema: str) -> None:
        if not self.has_user(username):
            raise Exception()

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        statement = sql.SQL("""
        grant usage on schema {schema} to {username};
        grant select on all tables in schema {schema} to {username};
        alter default privileges in schema {schema} grant select on tables to {username};
        """).format(schema=sql.Identifier(schema), username=sql.Identifier(username))

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def revoke_user_privileges(self, username: str, schema: str) -> None:
        if not self.has_user(username):
            return

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        # TODO Consider adding `reassign owned by {username} to {new_owner};`
        statement = sql.SQL("""
        alter default privileges for user {username} in schema {schema} revoke select on tables from {username};
        revoke select on all tables in schema {schema} from {username};
        revoke usage on schema {schema} from {username};
        """).format(schema=sql.Identifier(schema), username=sql.Identifier(username))

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

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

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        tables = [sql.SQL(str(PostgresRelation.from_string(table))) for table in tables]
        statement = sql.SQL("""
        create publication {publication} for table {tables};
        """).format(publication=sql.Identifier(publication), tables=sql.SQL(", ").join(tables))

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def drop_publication(self, publication: str, if_exists: bool | None = False) -> None:
        if not self.has_publication(publication):
            if if_exists:
                return
            else:
                raise PublicationNotFoundException(f"Publication '{publication}' not found")

        if self.settings.driver == "psycopg":
            from psycopg import sql
        else:
            from psycopg2 import sql

        statement = sql.SQL("""
        drop publication {publication};
        """).format(publication=sql.Identifier(publication))

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            conn.commit()

    def list_publications(self) -> list[str]:
        statement = """
        select pubname as publication
        from pg_catalog.pg_publication;
        """

        with self.create_client() as (conn, cur):
            cur.execute(statement)
            result = [row[0] for row in cur.fetchall()]

        return result
