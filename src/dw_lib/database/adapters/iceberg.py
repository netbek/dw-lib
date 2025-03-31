from ...types import AdapterType, DuckDBSettings, IcebergCatalog
from ..adapters.base import BaseAdapter
from .duckdb import DuckDBAdapter
from functools import lru_cache
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.table import Table
from pyiceberg.typedef import Identifier
from typing import List, Optional

import pyarrow


class IcebergAdapter(BaseAdapter):
    def __init__(self, settings: IcebergCatalog) -> None:
        self.type = AdapterType.ICEBERG
        self.catalog = SqlCatalog("default", **settings.model_dump(by_alias=True))
        self.default_namespace = "default"  # TODO Remove in favour of settings value
        super().__init__(settings)

    def can_connect(self): ...

    def create_client(self): ...

    def create_database(self): ...

    def create_namespace(self, namespace: str | Identifier):
        self.catalog.create_namespace(namespace)

    def create_publication(self): ...

    def create_schema(self): ...

    def create_session(self): ...

    def create_table(
        self,
        table: str,
        statement: str,
        namespace: Optional[str | Identifier] = None,
        replace: Optional[bool] = False,
    ) -> Table:
        if namespace is None:
            namespace = self.default_namespace

        if self.has_table(table=table, namespace=namespace):
            if replace:
                self.drop_table(table=table, namespace=namespace)
            else:
                return  # TODO Return table

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

    def create_url(self): ...

    def create_user(self): ...

    def drop_database(self): ...

    def drop_namespace(self, namespace: str | Identifier):
        self.catalog.drop_namespace(namespace)

    def drop_publication(self): ...

    def drop_schema(self): ...

    def drop_table(self, table: str, namespace: str | Identifier):
        if namespace is None:
            namespace = self.default_namespace

        if not self.has_table(table=table, namespace=namespace):
            return

        self.catalog.drop_table(f"{namespace}.{table}")

    def drop_tables(self): ...

    def drop_user(self): ...

    def get_create_table_statement(self): ...

    def get_table(self): ...

    def get_table_replica_identity(self): ...

    def grant_user_privileges(self): ...

    def has_database(self): ...

    def has_publication(self): ...

    def has_schema(self): ...

    def has_table(self, table: str, namespace: Optional[str | Identifier] = None) -> bool:
        if namespace is None:
            namespace = self.default_namespace

        for _namespace, _table in self.list_tables(namespace):
            if _namespace == namespace and _table == table:
                return True

        return False

    def has_user(self): ...

    def list_publications(self): ...

    def list_tables(self, namespace: Optional[str | Identifier] = None) -> List[Identifier]:
        if namespace is None:
            namespace = self.default_namespace

        return self.catalog.list_tables(namespace)

    def list_user_privileges(self): ...

    def revoke_user_privileges(self): ...

    def set_table_replica_identity(self): ...

    def truncate_table(self): ...
