from ..raw.raw_measurement import RawMeasurement
from clickhouse_sqlalchemy import engines, types
from decimal import Decimal
from dw_lib.builder.clickhouse import BaseTable, Materialization
from sqlalchemy import Column
from sqlmodel import Field


class Measurement(BaseTable, table=True):
    __tablename__ = "measurement"
    __table_args__ = (
        engines.MergeTree(order_by=("device_id", "timestamp")),
        {"schema": "analytics"},
    )

    device_id: int = Field(sa_column=Column(types.Int32, primary_key=True))
    timestamp: str = Field(sa_column=Column(types.DateTime64(6), primary_key=True))
    temperature: Decimal | None = Field(
        sa_column=Column(types.Nullable(types.Decimal)), default=None
    )

    __depends_on__ = [RawMeasurement]
    __materialization__ = Materialization.DELETE_INSERT
    __unique_key__ = ("device_id", "timestamp")
    __sql__ = """
    SELECT
        42 AS device_id,
        now64() AS timestamp,
        23 AS temperature
    """
