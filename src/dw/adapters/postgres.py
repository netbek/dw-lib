from collections.abc import Generator
from contextlib import contextmanager
from dw.adapters.base import BaseAdapter
from dw.types import AdapterType, PostgresSettings
from sqlalchemy import URL
from sqlmodel import Session
from typing import Any

import psycopg2


class PostgresAdapter(BaseAdapter):
    def __init__(self, settings: PostgresSettings) -> None:
        self.type = AdapterType.POSTGRES
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
            row = cur.fetchone()

        return row == (1,)
