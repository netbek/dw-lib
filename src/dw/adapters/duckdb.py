from collections.abc import Generator
from contextlib import contextmanager
from dw.adapters.base import BaseAdapter
from dw.types import AdapterType, DuckDBSettings
from pathlib import Path
from sqlalchemy import URL
from typing import Any

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

        # Apply settings before installing extensions, in case a custom home directory is specified
        for name, value in self.settings.settings.items():
            # Generate quoted value because SET statement does not support parameters
            if isinstance(value, int):
                quoted_value = value
            else:
                quoted_value = f"'{value}'"

            conn.execute(f"set {name} to {quoted_value};")

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
        raise NotImplementedError

    def can_connect(self) -> bool:
        with self.create_client() as conn:
            conn.execute("select 1;")
            row = conn.fetchone()

        return row == (1,)
