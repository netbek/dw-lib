from collections.abc import Generator
from dw_lib.database import (
    ClickHouseAdapter,
    ClickHouseRelation,
    PostgresAdapter,
    PostgresRelation,
)
from dw_lib.peerdb import PeerDB
from typing import Any

import pydash
import pytest
import time


def table_kwargs(destination_adapter: ClickHouseAdapter | PostgresAdapter, identifier: str) -> dict:
    """Return the keyword arguments for has_table/drop_table of a destination table identifier."""
    relation_class = (
        ClickHouseRelation
        if isinstance(destination_adapter, ClickHouseAdapter)
        else PostgresRelation
    )
    relation = relation_class.from_string(identifier)

    kwargs = {"table": relation.table}

    if getattr(relation, "schema_", None):
        kwargs["schema"] = relation.schema_

    return kwargs


def wait_for_table(
    destination_adapter: ClickHouseAdapter | PostgresAdapter,
    table_kwargs: dict,
    timeout: int = 90,
) -> None:
    """Wait until the table exists in the destination database."""
    for _ in range(timeout):
        if destination_adapter.has_table(**table_kwargs):
            return
        time.sleep(1)

    raise AssertionError(f"Table '{table_kwargs['table']}' was not created within {timeout}s")


@pytest.fixture(scope="function")
def extra_mirror(peerdb: PeerDB) -> dict:
    """A mirror that is not part of the local PeerDB configuration."""
    mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")
    destination_identifier = mirror.table_mappings[0].destination_table_identifier
    prefix = destination_identifier.rsplit(".", 1)[0] + "." if "." in destination_identifier else ""

    extra = mirror.model_dump()
    extra["flow_job_name"] = "extra_mirror"
    extra["table_mappings"] = [
        {
            "source_table_identifier": "public.table_1",
            "destination_table_identifier": f"{prefix}extra_table_1",
            "exclude": None,
        },
    ]

    return extra


@pytest.fixture(scope="function")
def mirror_with_destination_table(
    peers: None,
    peerdb: PeerDB,
    postgres_adapter: PostgresAdapter,
    destination_adapter: ClickHouseAdapter | PostgresAdapter,
) -> Generator[Any, Any]:
    """Create the 'cdc_one' mirror, trigger a CDC batch and wait for the destination table."""
    mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == "cdc_one")

    peerdb.create_mirror(mirror.model_dump())
    peerdb.wait_for_mirror_status(mirror.flow_job_name, {"STATUS_RUNNING"})

    with postgres_adapter.create_client(autocommit=True) as (_, cur):
        cur.execute(
            "insert into table_1 (id, username, password, age, modified_at) "
            "values (999, 'user_999', 'password', 30, now()) "
            "on conflict (id) do nothing;"
        )

    wait_for_table(
        destination_adapter,
        table_kwargs(destination_adapter, mirror.table_mappings[0].destination_table_identifier),
    )

    yield None
