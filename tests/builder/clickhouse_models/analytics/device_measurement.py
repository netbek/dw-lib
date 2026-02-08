from .device import Device
from .measurement import Measurement
from dw_lib.builder.clickhouse import BaseView


class DeviceMeasurement(BaseView):
    __tablename__ = "device_measurement"
    __table_args__ = {"schema": "analytics"}
    __sql__ = f"""
    SELECT
        m.device_id AS device_id,
        m.temperature AS temperature
    FROM {Measurement} AS m
    INNER JOIN {Device} AS d ON d.id = m.device_id
    WHERE m.id = {{device_id:Int32}}
    """
