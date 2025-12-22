from ...types import DuckDBSettings
from ..adapters.base import BaseAdapter
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import URL
from sqlglot.dialects.dialect import Dialects
from sqlmodel import SQLModel, Table
from typing import Any, Literal

import duckdb


class DuckDBAdapter(BaseAdapter):
    def __init__(self, settings: DuckDBSettings) -> None:
        self.dialect = Dialects.DUCKDB
        super().__init__(settings)

    @classmethod
    def create_url(cls, database: Path | str) -> URL:
        return URL.create("duckdb", database=database)

    @property
    def url(self) -> URL:
        return self.create_url(self.settings.database)

    @contextmanager
    def create_client(self) -> Generator[duckdb.DuckDBPyConnection, Any, None]:
        conn = duckdb.connect(self.settings.database)

        if self.settings.settings:
            # Apply settings before installing extensions, in case a custom home directory is specified
            for name, value in self.settings.settings.model_dump().items():
                # Generate quoted value because SET statement does not support parameters
                if isinstance(value, int):
                    quoted_value = value
                else:
                    quoted_value = f"'{value}'"

                statement = f"set {name} to {quoted_value};"
                conn.execute(statement)

        if self.settings.extensions:
            for extension in self.settings.extensions:
                statement = f"""
                install {extension};
                load {extension};
                """
                conn.execute(statement)

        yield conn

        conn.close()

    @contextmanager
    def create_session(self):
        raise NotImplementedError()

    def can_connect(self) -> bool:
        with self.create_client() as conn:
            conn.execute("select 1;")
            result = conn.fetchone() == (1,)

        return result

    def has_database(self, database: str) -> bool:
        raise NotImplementedError()

    def create_database(
        self, database: str, if_exists: Literal["fail", "replace"] = "fail"
    ) -> None:
        raise NotImplementedError()

    def drop_database(self, database: str, if_exists: bool | None = False) -> None:
        raise NotImplementedError()

    def has_schema(self, schema: str, database: str | None = None):
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

    def has_table(self, table: str, database: str | None = None, schema: str | None = None) -> bool:
        raise NotImplementedError()

    def create_table(
        self,
        table: str,
        statement: str,
        database: str | None = None,
        schema: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None:
        raise NotImplementedError()

    def make_create_table_statement_from_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> str:
        raise NotImplementedError()

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
        raise NotImplementedError()

    def truncate_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> None:
        raise NotImplementedError()

    def get_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> Table:
        raise NotImplementedError()

    def get_table_replica_identity(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> None:
        raise NotImplementedError()

    def set_table_replica_identity(
        self,
        table: str,
        replica_identity: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> None:
        raise NotImplementedError()

    def drop_tables(self, database: str | None = None, schema: str | None = None) -> None:
        raise NotImplementedError()

    def list_tables(self, database: str | None = None, schema: str | None = None) -> list[Table]:
        raise NotImplementedError()

    def has_user(self, username: str) -> bool:
        raise NotImplementedError()

    def create_user(
        self,
        username: str,
        password: str,
        options: dict | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None:
        raise NotImplementedError()

    def drop_user(self, username: str, if_exists: bool | None = False) -> None:
        raise NotImplementedError()

    def grant_user_privileges(self, username: str, schema: str) -> None:
        raise NotImplementedError()

    def revoke_user_privileges(self, username: str, schema: str) -> None:
        raise NotImplementedError()

    def list_user_privileges(self, username: str) -> list[tuple] | None:
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
