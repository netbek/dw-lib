from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dw_lib.types import TableStats
from pydantic import BaseModel
from sqlalchemy import create_engine, Engine, URL
from sqlalchemy.sql.schema import ForeignKeyConstraint
from sqlglot import exp, parse_one
from sqlglot.dialects.dialect import Dialects, DialectType
from sqlmodel import SQLModel, Table
from typing import Any, ClassVar, Generic, Literal, overload, TypeVar

T = TypeVar("T", bound=BaseModel)


class BaseRelation(BaseModel):
    dialect: ClassVar[DialectType] = ""

    @classmethod
    def _parse_to_parts(cls, identifier: str) -> list[str]:
        if identifier:
            expression = parse_one(identifier, read=cls.dialect, into=exp.Table)

            if isinstance(expression.this, exp.Identifier):
                parts = [expression.catalog, expression.db, expression.this.name]
            else:
                parts = [expression.this]

            return [part for part in parts if part]
        else:
            raise ValueError(f"Invalid table identifier: {identifier}")


class BaseAdapter(ABC, Generic[T]):
    dialect: Dialects
    settings_class: type[T]

    def __init__(self, settings: T | URL | str) -> None:
        if not isinstance(settings, self.settings_class):
            self.settings: T = self.settings_class.from_url(settings)
        else:
            self.settings: T = settings

    @abstractmethod
    def create_client(): ...

    @contextmanager
    def create_engine(self, url: URL | None = None) -> Generator[Engine, Any, None]:
        url = url or self.settings.to_sqlalchemy_url()
        engine = create_engine(url.render_as_string(hide_password=False), echo=False)

        yield engine

        engine.dispose()

    @contextmanager
    @abstractmethod
    def create_session(): ...

    @abstractmethod
    def can_connect(self) -> bool: ...

    @abstractmethod
    def has_database(self, database: str) -> bool: ...

    @abstractmethod
    def create_database(
        self, database: str, if_exists: Literal["fail", "replace"] = "fail"
    ) -> None: ...

    @abstractmethod
    def drop_database(self, database: str, if_exists: bool | None = False) -> None: ...

    @abstractmethod
    def has_schema(self, schema: str, database: str | None = None) -> bool: ...

    @abstractmethod
    def create_schema(
        self,
        schema: str,
        database: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None: ...

    @abstractmethod
    def drop_schema(
        self, schema: str, database: str | None = None, if_exists: bool | None = False
    ) -> None: ...

    @overload
    @abstractmethod
    def has_table(self, table: str, database: str | None = None) -> bool: ...

    @overload
    @abstractmethod
    def has_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> bool: ...

    @abstractmethod
    def has_table(self, *args, **kwargs) -> bool: ...

    @overload
    @abstractmethod
    def create_table(
        self,
        table: str,
        statement: str,
        database: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None: ...

    @overload
    @abstractmethod
    def create_table(
        self,
        table: str,
        statement: str,
        database: str | None = None,
        schema: str | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None: ...

    @abstractmethod
    def create_table(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def make_create_table_statement_from_table(
        self, table: str, database: str | None = None
    ) -> str: ...

    @overload
    @abstractmethod
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
    ) -> str: ...

    @abstractmethod
    def make_create_table_statement_from_table(self, *args, **kwargs) -> str: ...

    @overload
    @abstractmethod
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
    ) -> str: ...

    @overload
    @abstractmethod
    def make_create_table_statement_from_model(
        self,
        model: type[SQLModel],
        table: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        sql: str | None = None,
        if_not_exists: bool | None = False,
        replace: bool | None = False,
        pretty: bool = False,
        pad: int = 2,
        indent: int = 2,
    ) -> str: ...

    @abstractmethod
    def make_create_table_statement_from_model(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
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
    ) -> str: ...

    @overload
    @abstractmethod
    def make_create_view_statement_from_model(
        self,
        model: type[SQLModel],
        sql: str,
        table: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        if_not_exists: bool | None = False,
        replace: bool | None = False,
        pretty: bool = False,
        pad: int = 2,
        indent: int = 2,
    ) -> str: ...

    @abstractmethod
    def make_create_view_statement_from_model(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def drop_table(
        self, table: str, database: str | None = None, if_exists: bool | None = False
    ) -> None: ...

    @overload
    @abstractmethod
    def drop_table(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
        if_exists: bool | None = False,
    ) -> None: ...

    @abstractmethod
    def drop_table(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def truncate_table(self, table: str, database: str | None = None) -> None: ...

    @overload
    @abstractmethod
    def truncate_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> None: ...

    @abstractmethod
    def truncate_table(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def get_table(self, table: str, database: str | None = None) -> Table: ...

    @overload
    @abstractmethod
    def get_table(
        self, table: str, database: str | None = None, schema: str | None = None
    ) -> Table: ...

    @abstractmethod
    def get_table(self, *args, **kwargs) -> Table: ...

    @overload
    @abstractmethod
    def get_table_stats(self, table: str, database: str | None = None) -> TableStats: ...

    @overload
    @abstractmethod
    def get_table_stats(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> TableStats: ...

    @abstractmethod
    def get_table_stats(self, *args, **kwargs) -> TableStats:
        """Get statistics about every column in the table."""

    @overload
    @abstractmethod
    def get_table_replica_identity(self, table: str, database: str | None = None) -> None: ...

    @overload
    @abstractmethod
    def get_table_replica_identity(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> None: ...

    @abstractmethod
    def get_table_replica_identity(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def set_table_replica_identity(
        self, table: str, replica_identity: str, database: str | None = None
    ) -> None: ...

    @overload
    @abstractmethod
    def set_table_replica_identity(
        self,
        table: str,
        replica_identity: str,
        database: str | None = None,
        schema: str | None = None,
    ) -> None: ...

    @abstractmethod
    def set_table_replica_identity(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def drop_tables(self, database: str | None = None) -> None: ...

    @overload
    @abstractmethod
    def drop_tables(self, database: str | None = None, schema: str | None = None) -> None: ...

    @abstractmethod
    def drop_tables(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def list_tables(self, database: str | None = None) -> list[Table]: ...

    @overload
    @abstractmethod
    def list_tables(
        self, database: str | None = None, schema: str | None = None
    ) -> list[Table]: ...

    @abstractmethod
    def list_tables(self, *args, **kwargs) -> list[Table]: ...

    @abstractmethod
    def has_user(self, username: str) -> bool: ...

    @overload
    @abstractmethod
    def create_user(
        self, username: str, password: str, if_exists: Literal["fail", "replace"] = "fail"
    ) -> None: ...

    @overload
    @abstractmethod
    def create_user(
        self,
        username: str,
        password: str,
        options: dict | None = None,
        if_exists: Literal["fail", "replace"] = "fail",
    ) -> None: ...

    @abstractmethod
    def create_user(self, *args, **kwargs) -> None: ...

    @abstractmethod
    def drop_user(self, username: str, if_exists: bool | None = False) -> None: ...

    @overload
    @abstractmethod
    def grant_user_privileges(self, username: str, database: str) -> None: ...

    @overload
    @abstractmethod
    def grant_user_privileges(self, username: str, schema: str) -> None: ...

    @abstractmethod
    def grant_user_privileges(self, *args, **kwargs) -> None: ...

    @overload
    @abstractmethod
    def revoke_user_privileges(self, username: str, database: str) -> None: ...

    @overload
    @abstractmethod
    def revoke_user_privileges(self, username: str, schema: str) -> None: ...

    @abstractmethod
    def revoke_user_privileges(self, *args, **kwargs) -> None: ...

    @abstractmethod
    def list_user_privileges(self, username: str) -> list[tuple]: ...

    @abstractmethod
    def has_publication(self, publication: str) -> bool: ...

    @abstractmethod
    def create_publication(
        self, publication: str, tables: list[str], if_exists: Literal["fail", "replace"] = "fail"
    ) -> None: ...

    @abstractmethod
    def drop_publication(self, publication: str, if_exists: bool | None = False) -> None: ...

    @abstractmethod
    def list_publications(self) -> list[str]: ...
