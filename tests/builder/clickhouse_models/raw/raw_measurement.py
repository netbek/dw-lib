from dw_lib.builder.clickhouse import BaseTable, Materialization


class RawMeasurement(BaseTable):
    __tablename__ = "raw_measurement"
    __table_args__ = {"schema": "raw"}
    __materialization__ = Materialization.EXTERNAL
