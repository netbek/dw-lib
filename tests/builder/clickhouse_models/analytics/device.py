from clickhouse_sqlalchemy import engines, types
from dw_lib.builder.clickhouse import BaseTable
from sqlalchemy import Column
from sqlmodel import Field


class Device(BaseTable, table=True):
    __tablename__ = "device"
    __table_args__ = (
        engines.MergeTree(order_by=("id")),
        {"schema": "analytics"},
    )

    id: int = Field(sa_column=Column(types.Int32, primary_key=True))
