from dw_lib.types import ClickHouseSettings
from functools import lru_cache
from pydantic import BaseModel, Field


# The settings are hard-coded in this example. In a real app, these values would be loaded from
# the environment.
class DbtTargetSettings(BaseModel):
    driver: str = "http"
    host: str = "localhost"
    port: int = 28123
    username: str = "default"
    password: str = "default"
    database: str = "test"


def to_clickhouse_settings(dbt_target_settings: DbtTargetSettings) -> ClickHouseSettings:
    return ClickHouseSettings(
        host=dbt_target_settings.host,
        port=dbt_target_settings.port,
        username=dbt_target_settings.username,
        password=dbt_target_settings.password,
        database=dbt_target_settings.database,
        driver=dbt_target_settings.driver,
    )


class Settings(BaseModel):
    database: ClickHouseSettings = Field(
        default_factory=lambda: to_clickhouse_settings(DbtTargetSettings())
    )


@lru_cache
def get_settings():
    return Settings()
