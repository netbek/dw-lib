from ..conftest import DatabaseTest
from collections.abc import Generator
from dw_lib.database import ClickHouseAdapter, ClickHouseRelation
from typing import Any

import pytest


class CodeGenerationTest(DatabaseTest):
    @pytest.fixture(scope="function")
    def relation(
        self, clickhouse_adapter: ClickHouseAdapter
    ) -> Generator[ClickHouseRelation, Any, None]:
        yield ClickHouseRelation(database=clickhouse_adapter.settings.database, table="test_table")

    @pytest.fixture(scope="function")
    def table(
        self, clickhouse_adapter: ClickHouseAdapter, relation: ClickHouseRelation
    ) -> Generator[ClickHouseRelation, Any, None]:
        create_table_statement = f"""
create or replace table {relation}
(
    `uint64` UInt64,
    `int64` Int64,
    `uint32` UInt32,
    `int32` Int32,
    `uint16` UInt16,
    `int16` Int16,
    `uint8` UInt8,
    `int8` Int8,
    `decimal256` Decimal256(1),
    `decimal128` Decimal128(1),
    `decimal64` Decimal64(1),
    `decimal32` Decimal32(1),
    `decimal` Decimal,
    `float64` Float64,
    `float32` Float32,
    `bool` Boolean,
    `nullable_bool` Nullable(Boolean),
    `date32` Date32,
    `datetime` DateTime default now(),
    `nullable(datetime)` Nullable(DateTime),
    `datetime64` DateTime64(9) default now(),
    `nullable_datetime64` Nullable(DateTime64(9)),
    `string` String,
    `nullable_string` Nullable(String),
    `uuid` UUID,
    `nullable_uuid` Nullable(UUID),
    `_peerdb_synced_at` DateTime64(9) DEFAULT now64(),
    `_peerdb_is_deleted` Int8,
    `_peerdb_version` Int64
)
engine = MergeTree
primary key `uint64`
order by `uint64`
"""
        clickhouse_adapter.create_table(relation.table, create_table_statement)
        yield clickhouse_adapter.get_table(relation.table)
        clickhouse_adapter.drop_table(relation.table)
