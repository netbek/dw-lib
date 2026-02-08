from ..raw.raw_measurement import RawMeasurement
from dw_lib.builder.clickhouse import BaseView


class CleanMeasurement(BaseView):
    __tablename__ = "clean_measurement"
    __table_args__ = {"schema": "analytics"}
    __sql__ = f"""
    SELECT
        device_id,
        temperature
    FROM {RawMeasurement}
    WHERE
        device_id = 1
    """
