from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from sqlglot.dialects.dialect import Dialects
from typing import TypedDict


class CreateTableStatementOptions(TypedDict):
    schema: str | None = None
    if_not_exists: bool | None = False
    include_autoincrement: bool | None = False
    include_index: bool | None = False
    include_primary_key_constraint: bool | None = False
    include_foreign_key_constraint: bool | None = False
    include_unique_constraint: bool | None = False


class ClickHouseIdentifier:
    @classmethod
    def quote(cls, identifier: str) -> str:
        return f"`{identifier}`"

    @classmethod
    def unquote(cls, identifier: str) -> str:
        return identifier.strip("`")


class ClickHouseTableIdentifier(ClickHouseIdentifier, BaseModel):
    database: str | None = Field(default=None, serialization_alias="database")
    table: str = Field(serialization_alias="table")

    @classmethod
    def from_string(cls, identifier: str) -> "ClickHouseTableIdentifier":
        parts = [cls.unquote(part) for part in identifier.split(".")]

        if len(parts) == 2:
            return cls(database=parts[0], table=parts[1])
        elif len(parts) == 1:
            return cls(table=parts[0])
        else:
            raise ValueError()

    def to_string(self) -> str:
        if self.database is not None:
            return f"{self.quote(self.database)}.{self.quote(self.table)}"
        else:
            return self.quote(self.table)


class PostgresIdentifier:
    @classmethod
    def quote(cls, identifier: str) -> str:
        return f'"{identifier}"'

    @classmethod
    def unquote(cls, identifier: str) -> str:
        return identifier.strip('"')


class PostgresTableIdentifier(PostgresIdentifier, BaseModel):
    database: str | None = Field(default=None, serialization_alias="database")
    schema_: str | None = Field(default=None, serialization_alias="schema")
    table: str = Field(serialization_alias="table")

    @classmethod
    def from_string(cls, identifier: str) -> "PostgresTableIdentifier":
        parts = [cls.unquote(part) for part in identifier.split(".")]

        if len(parts) == 3:
            return cls(database=parts[0], schema_=parts[1], table=parts[2])
        elif len(parts) == 2:
            return cls(schema_=parts[0], table=parts[1])
        elif len(parts) == 1:
            return cls(table=parts[0])
        else:
            raise ValueError()

    def to_string(self) -> str:
        if self.database is not None and self.schema_ is not None:
            return (
                f"{self.quote(self.database)}.{self.quote(self.schema_)}.{self.quote(self.table)}"
            )
        elif self.schema_ is not None:
            return f"{self.quote(self.schema_)}.{self.quote(self.table)}"
        else:
            return self.quote(self.table)

    def is_fully_qualified(self) -> bool:
        return all([self.database, self.schema_, self.table])


class ClickHouseSettings(BaseSettings):
    host: str
    http_port: int
    tcp_port: int
    username: str
    password: str
    database: str
    secure: bool | None = Field(default=False)
    driver: str | None = Field(default=None)


class PostgresSettings(BaseSettings):
    host: str
    port: int
    username: str
    password: str
    database: str
    schema_: str = Field(default="public", serialization_alias="schema")


class DbtSettings(BaseSettings):
    directory: Path | str
    config: dict


class PeerDBSettings(BaseSettings):
    config_path: Path | str


class NotebookSettings(BaseSettings):
    directory: Path | str


class DbtResourceType(StrEnum):
    MODEL = "model"
    SEED = "seed"
    SOURCE = "source"


class DbtColumnMeta(BaseModel):
    sqlalchemy_type: str


class DbtColumn(BaseModel):
    data_type: str
    meta: DbtColumnMeta | None = None
    name: str


class DbtContract(BaseModel):
    alias_types: bool
    enforced: bool


class DbtDependsOn(BaseModel):
    macros: list[str] | None = None
    nodes: list[str] | None = None


class DbtDocs(BaseModel):
    node_color: str | None = None
    show: bool


class DbtPersistDocs(BaseModel):
    columns: bool | None = None


class DbtTableMeta(BaseModel):
    python_class: str


class DbtTable(BaseModel):
    columns: list[DbtColumn] | None = None
    loaded_at_field: str | None = None
    meta: DbtTableMeta | None = None
    name: str


class DbtBaseResource(BaseModel):
    name: str
    original_file_path: str
    package_name: str
    resource_type: DbtResourceType
    tags: list[str]
    unique_id: str


class DbtModelConfig(BaseModel):
    access: str
    alias: str | None = None
    batch_filter: str | None = None
    batch_size: int | None = None
    column_types: dict[str, str]
    contract: DbtContract
    database: str | None = None
    docs: DbtDocs
    enabled: bool
    engine: str | None = None
    full_refresh: bool | None = False
    grants: dict[str, list[str]]
    group: str | None = None
    incremental_strategy: str | None = None
    materialized: str
    meta: dict[str, str | int | float | bool | None]
    on_configuration_change: str
    on_schema_change: str
    order_by: str | None = None
    packages: list[str]
    persist_docs: DbtPersistDocs
    post_hook: list[str] | None = None
    pre_hook: list[str] | None = None
    quoting: dict[str, bool]
    range_max: str | None = None
    range_min: str | None = None
    schema_: str | None = Field(default=None, serialization_alias="schema")
    tags: list[str]
    unique_key: str | None = None


class DbtModel(DbtBaseResource):
    alias: str
    config: DbtModelConfig
    depends_on: DbtDependsOn


class DbtSeedConfig(BaseModel):
    alias: str | None = None
    column_types: dict[str, str]
    contract: DbtContract
    database: str | None = None
    delimiter: str
    docs: DbtDocs
    enabled: bool
    full_refresh: bool | None = False
    grants: dict[str, list[str]]
    group: str | None = None
    incremental_strategy: str | None = None
    materialized: str
    meta: dict[str, str | int | float | bool | None]
    on_configuration_change: str
    on_schema_change: str
    packages: list[str]
    persist_docs: DbtPersistDocs
    post_hook: list[str] | None = None
    pre_hook: list[str] | None = None
    quote_columns: bool | None = None
    quoting: dict[str, bool]
    schema_: str | None = Field(default=None, serialization_alias="schema")
    tags: list[str]
    unique_key: str | None = None


class DbtSeed(DbtBaseResource):
    alias: str
    config: DbtSeedConfig
    depends_on: DbtDependsOn


class DbtSourceConfig(BaseModel):
    enabled: bool


class DbtSource(DbtBaseResource):
    config: DbtSourceConfig
    original_config: DbtTable | None = None
    source_name: str
