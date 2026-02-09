from clickhouse_sqlalchemy import engines, types
from dw_lib.builder.clickhouse import BaseTable
from sqlalchemy import Column
from sqlmodel import Field


class Device(BaseTable, table=True):
    __tablename__ = "device"
    __table_args__ = (
        engines.MergeTree(order_by=("id")),
        {"schema": "staging"},
    )

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))

    __unique_key__ = ("device_id",)
    __sql__ = """
    SELECT
        42 AS id
    """
