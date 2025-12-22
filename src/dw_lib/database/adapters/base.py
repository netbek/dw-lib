from ...typing import CreateTableStatementOptions
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from pydantic import BaseModel
from sqlalchemy import create_engine, Engine, URL
from sqlmodel import Table
from typing import Any, Literal, overload


class BaseAdapter(ABC):
    def __init__(self, settings: BaseModel) -> None:
        self.settings = settings

    @overload
    @classmethod
    @abstractmethod
    def create_url(
        cls,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
        driver: str | None = None,
        secure: bool | None = None,
    ) -> URL: ...

    @overload
    @classmethod
    @abstractmethod
    def create_url(cls, database: str) -> URL: ...

    @overload
    @classmethod
    @abstractmethod
    def create_url(
        cls, host: str, port: int, username: str, password: str, database: str
    ) -> URL: ...

    @classmethod
    @abstractmethod
    def create_url(cls, *args, **kwargs) -> URL: ...

    @abstractmethod
    def create_client(): ...

    @contextmanager
    def create_engine(self, url: URL | None = None) -> Generator[Engine, Any, None]:
        engine = create_engine((url or self.url).render_as_string(hide_password=False), echo=False)

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
    def get_create_table_statement(self, table: str, database: str | None = None) -> None: ...

    @overload
    @abstractmethod
    def get_create_table_statement(
        self,
        table: str,
        database: str | None = None,
        schema: str | None = None,
        options: CreateTableStatementOptions | None = None,
    ) -> None: ...

    @abstractmethod
    def get_create_table_statement(self, *args, **kwargs) -> None: ...

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
