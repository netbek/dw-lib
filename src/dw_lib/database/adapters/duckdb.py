from ...types import AdapterType, DuckDBSettings, IcebergSettings
from ..adapters.base import BaseAdapter
from ..utils import escape_sql_value
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import URL
from sqlmodel import Table
from typing import Any, List, Optional
from urllib.parse import urlparse

import duckdb


class DuckDBAdapter(BaseAdapter):
    def __init__(self, settings: DuckDBSettings) -> None:
        self.type = AdapterType.DUCKDB
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

    def create_database(self, database: str, replace: Optional[bool] = False) -> None:
        raise NotImplementedError()

    def drop_database(self, database: str) -> None:
        raise NotImplementedError()

    def has_schema(self, schema: str, database: Optional[str] = None):
        raise NotImplementedError()

    def create_schema(
        self,
        schema: str,
        database: Optional[str] = None,
        replace: Optional[bool] = False,
    ) -> None:
        raise NotImplementedError()

    def drop_schema(self, schema: str, database: Optional[str] = None) -> None:
        raise NotImplementedError()

    def has_table(
        self, table: str, database: Optional[str] = None, schema: Optional[str] = None
    ) -> bool:
        raise NotImplementedError()

    def create_table(
        self,
        table: str,
        statement: str,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        replace: Optional[bool] = False,
    ) -> None:
        raise NotImplementedError()

    def get_create_table_statement(
        self, table: str, database: Optional[str] = None, schema: Optional[str] = None
    ) -> None:
        raise NotImplementedError()

    def drop_table(
        self, table: str, database: Optional[str] = None, schema: Optional[str] = None
    ) -> None:
        raise NotImplementedError()

    def truncate_table(
        self, table: str, database: Optional[str] = None, schema: Optional[str] = None
    ) -> None:
        raise NotImplementedError()

    def get_table(
        self, table: str, database: Optional[str] = None, schema: Optional[str] = None
    ) -> Table:
        raise NotImplementedError()

    def get_table_replica_identity(
        self,
        table: str,
        database: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        raise NotImplementedError()

    def set_table_replica_identity(
        self,
        table: str,
        replica_identity: str,
        database: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        raise NotImplementedError()

    def drop_tables(self, database: Optional[str] = None, schema: Optional[str] = None) -> None:
        raise NotImplementedError()

    def list_tables(
        self, database: Optional[str] = None, schema: Optional[str] = None
    ) -> List[Table]:
        raise NotImplementedError()

    def has_user(self, username: str) -> bool:
        raise NotImplementedError()

    def create_user(
        self,
        username: str,
        password: str,
        options: Optional[dict] = None,
        replace: Optional[bool] = False,
    ) -> None:
        raise NotImplementedError()

    def drop_user(self, username: str) -> None:
        raise NotImplementedError()

    def grant_user_privileges(self, username: str, schema: str) -> None:
        raise NotImplementedError()

    def revoke_user_privileges(self, username: str, schema: str) -> None:
        raise NotImplementedError()

    def list_user_privileges(self, username: str) -> List[tuple] | None:
        raise NotImplementedError()

    def has_publication(self, publication: str) -> bool:
        raise NotImplementedError()

    def create_publication(self, publication: str, tables: List[str], replace=False) -> None:
        raise NotImplementedError()

    def drop_publication(self, publication: str) -> None:
        raise NotImplementedError()

    def list_publications(self) -> List[str]:
        raise NotImplementedError()

    def get_create_secret_statement_for_iceberg(
        self,
        iceberg_settings: IcebergSettings,
        secret: Optional[str] = "s3_secret",
        replace: Optional[bool] = False,
    ):
        parsed_s3_endpoint = urlparse(iceberg_settings.s3_endpoint)

        if parsed_s3_endpoint.scheme == "https":
            use_ssl = "true"
        else:
            use_ssl = "false"

        if iceberg_settings.is_minio:
            url_style = "path"
        else:
            url_style = "vhost"

        statement = f"""
        {"create or replace" if replace else "create"} secret {secret} (
            type s3,
            key_id '{escape_sql_value(iceberg_settings.s3_access_key_id)}',
            secret '{escape_sql_value(iceberg_settings.s3_secret_access_key)}',
            region '{escape_sql_value(iceberg_settings.s3_region)}',
            endpoint '{escape_sql_value(parsed_s3_endpoint.netloc)}',
            url_style '{escape_sql_value(url_style)}',
            use_ssl '{escape_sql_value(use_ssl)}'
        );
        """

        return statement
