from ...types import AdapterType, DuckDBSettings, IcebergSettings
from ..adapters.base import BaseAdapter
from .duckdb import DuckDBAdapter
from functools import lru_cache
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.table import Table
from pyiceberg.typedef import Identifier, Properties
from typing import List, Optional

import pyarrow


class IcebergAdapter(BaseAdapter):
    def __init__(self, settings: IcebergSettings) -> None:
        self.type = AdapterType.ICEBERG
        self.catalog = SqlCatalog(settings.catalog, **settings.model_dump(by_alias=True))
        super().__init__(settings)

    def create_url(self):
        raise NotImplementedError()

    def create_client(self):
        raise NotImplementedError()

    def create_session(self):
        raise NotImplementedError()

    def can_connect(self):
        raise NotImplementedError()

    def has_database(self):
        raise NotImplementedError()

    def create_database(self):
        raise NotImplementedError()

    def drop_database(self):
        raise NotImplementedError()

    def has_schema(self):
        raise NotImplementedError()

    def create_schema(self):
        raise NotImplementedError()

    def drop_schema(self):
        raise NotImplementedError()

    def has_namespace(self, namespace: str) -> bool:
        for identifier in self.catalog.list_namespaces():
            if identifier[0] == namespace:
                return True

        return False

    def create_namespace(
        self,
        namespace: str,
        properties: Optional[Properties] = None,
        replace: Optional[bool] = False,
    ):
        if self.has_namespace(namespace):
            if replace:
                self.drop_namespace(namespace)
            else:
                return
        else:
            self.catalog.create_namespace(namespace, properties=properties)

    def drop_namespace(self, namespace: str, cascade: Optional[bool] = False):
        if cascade:
            self.drop_tables(namespace)

        self.catalog.drop_namespace(namespace)

    def has_table(self, table: str, namespace: Optional[str] = None) -> bool:
        if namespace is None:
            namespace = self.settings.namespace

        return self.catalog.table_exists(f"{namespace}.{table}")

    def create_table(
        self,
        table: str,
        statement: str,
        namespace: Optional[str] = None,
        replace: Optional[bool] = False,
    ) -> Table:
        if namespace is None:
            namespace = self.settings.namespace

        if self.has_table(table=table, namespace=namespace):
            if replace:
                self.drop_table(table=table, namespace=namespace)
            else:
                return self.catalog.load_table(f"{namespace}.{table}")

        schema = self._get_arrow_table_schema(table, statement)

        return self.catalog.create_table(f"{namespace}.{table}", schema=schema)

    @lru_cache
    def _get_arrow_table_schema(self, table: str, statement: str) -> pyarrow.lib.Table:
        duckdb_adapter = DuckDBAdapter(DuckDBSettings(database=":memory:"))

        with duckdb_adapter.create_client() as conn:
            conn.execute(statement)
            conn.execute(f"select * from {table} limit 1;")
            arrow_table = conn.fetch_arrow_table()

        return arrow_table.schema

    def get_create_table_statement(self):
        raise NotImplementedError()

    def drop_table(self, table: str, namespace: Optional[str] = None):
        if namespace is None:
            namespace = self.settings.namespace

        if not self.has_table(table=table, namespace=namespace):
            return

        self.catalog.drop_table(f"{namespace}.{table}")

    def truncate_table(self):
        raise NotImplementedError()

    def get_table(self, table: str, namespace: Optional[str] = None) -> Table:
        if namespace is None:
            namespace = self.settings.namespace

        return self.catalog.load_table(f"{namespace}.{table}")

    def get_table_replica_identity(self):
        raise NotImplementedError()

    def set_table_replica_identity(self):
        raise NotImplementedError()

    def drop_tables(self, namespace: Optional[str] = None) -> None:
        if namespace is None:
            namespace = self.settings.namespace

        for namespace, table in self.list_tables(namespace=namespace):
            self.drop_table(table, namespace=namespace)

    def list_tables(self, namespace: Optional[str] = None) -> List[Identifier]:
        if namespace is None:
            namespace = self.settings.namespace

        return self.catalog.list_tables(namespace)

    def has_user(self):
        raise NotImplementedError()

    def create_user(self):
        raise NotImplementedError()

    def drop_user(self):
        raise NotImplementedError()

    def grant_user_privileges(self):
        raise NotImplementedError()

    def revoke_user_privileges(self):
        raise NotImplementedError()

    def list_user_privileges(self):
        raise NotImplementedError()

    def has_publication(self):
        raise NotImplementedError()

    def create_publication(self):
        raise NotImplementedError()

    def drop_publication(self):
        raise NotImplementedError()

    def list_publications(self):
        raise NotImplementedError()
