from dw import PostgresAdapter, PostgresSettings
from sqlalchemy import text

import pytest


class TestPostgresAdapter:
    @pytest.fixture(scope="class")
    def postgres_adapter(self):
        settings = PostgresSettings(
            host="postgres", port=5432, username="postgres", password="postgres", database="test"
        )
        yield PostgresAdapter(settings)

    def test_create_url(self, postgres_adapter: PostgresAdapter):
        url = postgres_adapter.create_url(
            host="localhost", port=5432, username="guest", password="secret", database="data"
        )
        assert str(url) == "postgresql://guest:***@localhost:5432/data"
        assert (
            url.render_as_string(hide_password=False)
            == "postgresql://guest:secret@localhost:5432/data"
        )

    def test_create_client(self, postgres_adapter: PostgresAdapter):
        with postgres_adapter.create_client() as (conn, cur):
            cur.execute(
                "select 1 from information_schema.schemata where catalog_name = %s limit 1;",
                [postgres_adapter.settings.database],
            )
            actual = cur.fetchall()
        assert actual == [(1,)]

    def test_create_session(self, postgres_adapter: PostgresAdapter):
        with postgres_adapter.create_session() as session:
            actual = session.exec(
                text(
                    "select 1 from information_schema.schemata where catalog_name = :database limit 1;"
                ).bindparams(database=postgres_adapter.settings.database)
            ).all()
        assert actual == [(1,)]
