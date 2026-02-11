from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, SecretStr
from pydantic_settings import BaseSettings
from sqlglot import exp, parse_one
from sqlglot.dialects.dialect import Dialects, DialectType
from typing import ClassVar

import math
import psutil


class BaseRelation(BaseModel):
    dialect: ClassVar[DialectType] = ""

    @classmethod
    def _parse_to_parts(cls, identifier: str) -> list[str]:
        if identifier:
            expression = parse_one(identifier, read=cls.dialect, into=exp.Table)

            if isinstance(expression.this, exp.Identifier):
                parts = [expression.catalog, expression.db, expression.this.name]
            else:
                parts = [expression.this]

            return [part for part in parts if part]
        else:
            raise ValueError(f"Invalid table identifier: {identifier}")


class ClickHouseRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.CLICKHOUSE
    database: str | None = Field(default=None)
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> "ClickHouseRelation":
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 2:
            return cls(database=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


class PostgresRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.POSTGRES
    database: str | None = Field(default=None)
    schema_: str | None = Field(default=None, serialization_alias="schema")
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> "PostgresRelation":
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 3:
            return cls(database=parts[0], schema_=parts[1], table=parts[2])
        elif len(parts) == 2:
            return cls(schema_=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.schema_) if self.schema_ else None,
            catalog=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


class DuckDBRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.DUCKDB
    database: str | None = Field(default=None)
    schema_: str | None = Field(default=None, serialization_alias="schema")
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> "DuckDBRelation":
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 3:
            return cls(database=parts[0], schema_=parts[1], table=parts[2])
        elif len(parts) == 2:
            return cls(schema_=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.schema_) if self.schema_ else None,
            catalog=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


def calculate_memory_limit(percent) -> str:
    amount = round(psutil.virtual_memory().total / (1024**3) * percent / 100, 1)
    return f"{amount}GB"


def calculate_threads(percent) -> int:
    return max(1, int(math.floor(psutil.cpu_count(logical=True) * percent / 100)))


# Default values from https://duckdb.org/docs/stable/configuration/overview.html#global-configuration-options
class DuckDBSystemSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    memory_limit: str | None = calculate_memory_limit(80)
    threads: int | str | None = calculate_threads(100)

    @field_validator("memory_limit", mode="before")
    @classmethod
    def convert_memory_limit(cls, value):
        if isinstance(value, str) and value.endswith("%"):
            try:
                percent = float(value.strip("%"))
                return calculate_memory_limit(percent)
            except ValueError:
                raise ValueError("Invalid percentage format for memory_limit.")
        return value

    @field_validator("threads", mode="before")
    @classmethod
    def convert_threads(cls, value):
        if isinstance(value, str) and value.endswith("%"):
            try:
                percent = float(value.strip("%"))
                return calculate_threads(percent)
            except ValueError:
                raise ValueError("Invalid percentage format for threads.")
        return value


class ClickHouseSettings(BaseSettings):
    host: str
    http_port: int
    tcp_port: int
    username: str
    password: SecretStr
    database: str
    driver: str | None = Field(default=None)


class DuckDBSettings(BaseSettings):
    database: Path | str
    schema_: str = Field(default="main", serialization_alias="schema")
    extensions: list[str] | None = None
    settings: DuckDBSystemSettings | None = None


class PostgresSettings(BaseSettings):
    host: str
    port: int
    username: str
    password: SecretStr
    database: str
    schema_: str = Field(default="public", serialization_alias="schema")


class S3Settings(BaseSettings):
    key_id: str
    secret: SecretStr
    region: str
    endpoint: str
    use_ssl: bool
    url_style: str = "path"
    bucket: str
    prefix: str | None = None


class DbtSettings(BaseSettings):
    directory: Path | str
    config: dict


class PeerDBSettings(BaseSettings):
    config_path: Path | str


class NotebookSettings(BaseSettings):
    directory: Path | str
