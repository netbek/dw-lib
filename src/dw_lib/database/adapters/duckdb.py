from ...types import TableStats
from ..adapters.base import BaseAdapter, BaseRelation
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import make_url, URL
from sqlglot import exp
from sqlglot.dialects.dialect import Dialects, DialectType
from sqlmodel import SQLModel, Table
from typing import Any, ClassVar, Literal, Self

import duckdb
import math
import psutil


def calculate_memory_limit(percent) -> str:
    amount = round(psutil.virtual_memory().total / (1024**3) * percent / 100, 1)
    return f"{amount}GB"


def calculate_threads(percent) -> int:
    return max(1, int(math.floor(psutil.cpu_count(logical=True) * percent / 100)))


class DuckDBSystemSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    memory_limit: str | None = calculate_memory_limit(80)
    threads: int | str | None = calculate_threads(100)

    @field_validator("memory_limit", mode="before")
    @classmethod
    def convert_memory_limit(cls, value):
        if isinstance(value, str) and value.endswith("%"):
            try:
                percent = float(value.strip("%"))
                return calculate_memory_limit(percent)
            except ValueError:
                raise ValueError("Invalid percentage format for memory_limit.")
        return value

    @field_validator("threads", mode="before")
    @classmethod
    def convert_threads(cls, value):
        if isinstance(value, str) and value.endswith("%"):
            try:
                percent = float(value.strip("%"))
                return calculate_threads(percent)
            except ValueError:
                raise ValueError("Invalid percentage format for threads.")
        return value


class DuckDBSettings(BaseModel):
    database: Path | str
    schema_: str = Field(default="main", serialization_alias="schema")
    extensions: list[str] | None = None
    settings: DuckDBSystemSettings | None = None

    @classmethod
    def from_url(cls, url: URL | str) -> Self:
        url = make_url(url)

        return cls(database=url.database)

    def to_sqlalchemy_url(self) -> URL:
        return URL.create("duckdb", database=str(self.database))

    def to_string(self, hide_password: bool = True) -> str:
        return self.to_sqlalchemy_url().render_as_string(hide_password=hide_password)

    def __str__(self) -> str:
        return self.to_string()


class DuckDBRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.DUCKDB
    database: str | None = Field(default=None)
    schema_: str | None = Field(default=None, serialization_alias="schema")
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> Self:
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 3:
            return cls(database=parts[0], schema_=parts[1], table=parts[2])
        elif len(parts) == 2:
            return cls(schema_=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.schema_) if self.schema_ else None,
            catalog=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


class DuckDBAdapter(BaseAdapter[DuckDBSettings]):
    dialect = Dialects.DUCKDB
    settings_class = DuckDBSettings

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
        try:
            with self.create_client() as conn:
                conn.execute("select 1;")
                result = conn.fetchone() == (1,)
        except Exception:
            result = False

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
        raise NotImplementedError()

    def truncate_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> None:
        raise NotImplementedError()

    def get_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> Table:
        raise NotImplementedError()

    def get_table_stats(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> TableStats:
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
