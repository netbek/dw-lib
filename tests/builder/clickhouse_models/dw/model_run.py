from clickhouse_sqlalchemy import engines, types
from dw_lib.builder.clickhouse import BaseTable
from sqlalchemy import Column
from sqlmodel import Field, text


class ModelRun(BaseTable, table=True):
    __tablename__ = "model_run"
    __table_args__ = (
        engines.MergeTree(
            order_by=("id"), enable_block_number_column=1, enable_block_offset_column=1
        ),
        {"schema": "dw"},
    )

    id: str = Field(sa_column=Column(types.UUID, primary_key=True))
    invocation_id: str = Field(sa_column=Column(types.UUID))
    model_name: str = Field(sa_column=Column(types.LowCardinality(types.String)))
    started_at: str = Field(sa_column=Column(types.DateTime64(6), server_default=text("now64(6)")))
    duration: int = Field(sa_column=Column(types.UInt64, comment="Duration in milliseconds."))
    status: str = Field(sa_column=Column(types.LowCardinality(types.String)))
    message: str = Field(sa_column=Column(types.String))
