from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import Any, TypedDict

import math
import psutil


class AdapterType(StrEnum):
    CLICKHOUSE = "clickhouse"
    DUCKDB = "duckdb"
    POSTGRES = "postgres"


class TableIndexType(StrEnum):
    BTREE = "btree"


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


class DuckDBTableIdentifier(PostgresTableIdentifier): ...


ADAPTER_TYPE_TO_PEERDB_TYPE_MAP = {
    AdapterType.CLICKHOUSE: 8,
    AdapterType.POSTGRES: 3,
}

ADAPTER_TYPE_TO_TABLE_IDENTIFIER_MAP = {
    AdapterType.DUCKDB: DuckDBTableIdentifier,
    AdapterType.POSTGRES: PostgresTableIdentifier,
}


def table_identifier_from_string(
    adapter_type: AdapterType, identifier: str
) -> DuckDBTableIdentifier | PostgresTableIdentifier:
    class_ = ADAPTER_TYPE_TO_TABLE_IDENTIFIER_MAP[adapter_type]
    return class_.from_string(identifier)


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
    password: str
    database: str
    secure: bool | None = Field(default=False)
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
    password: str
    database: str
    schema_: str = Field(default="public", serialization_alias="schema")


class DbtSettings(BaseSettings):
    directory: Path | str
    config: dict


class PeerDBSettings(BaseSettings):
    config_path: Path | str


class PrefectSettings(BaseSettings):
    config: dict


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


class ZincDuckDBPeerSettings(DuckDBSettings):
    model_config = ConfigDict(use_enum_values=True)

    type: str


class ZincPostgresPeerSettings(PostgresSettings):
    model_config = ConfigDict(use_enum_values=True)

    type: str


class ZincMirrorPeersSettings(BaseModel):
    source: str
    destination: str


class ZincMirrorTableIndexSettings(BaseModel):
    name: str | None = None
    columns: list[str] = Field(min_length=1)
    type: TableIndexType = TableIndexType.BTREE

    @classmethod
    def generate_index_name(cls, adapter_type: AdapterType, table: str, columns: list[str]) -> str:
        table_identifier = table_identifier_from_string(adapter_type, table)
        return f"ix_{table_identifier.table}_{'_'.join(columns)}"


class ZincMirrorTableSettings(BaseModel):
    source: str
    destination: str
    query: str | None = None
    indexes: list[ZincMirrorTableIndexSettings] | None = []

    @classmethod
    def generate_query(cls, source: str) -> str:
        return f"select * from {source};"

    def model_post_init(self, __context: Any) -> None:
        if not self.query:
            self.query = self.generate_query(self.source)


class ZincMirrorSettings(BaseModel):
    peers: ZincMirrorPeersSettings
    tables: list[ZincMirrorTableSettings] = Field(min_length=1)


ZincPeersSettings = dict[str, ZincDuckDBPeerSettings | ZincPostgresPeerSettings]
ZincMirrorsSettings = dict[str, ZincMirrorSettings]


class ZincSettings(BaseModel):
    peers: ZincPeersSettings
    mirrors: ZincMirrorsSettings

    @field_validator("peers", mode="after")
    @classmethod
    def validate_peers(cls, peers: ZincPeersSettings) -> ZincPeersSettings:
        types = {peer.type for peer in peers.values()}

        if types != {AdapterType.DUCKDB, AdapterType.POSTGRES}:
            raise ValueError(
                f"Peer types must be '{AdapterType.DUCKDB}' and '{AdapterType.POSTGRES}'."
            )

        return peers

    @model_validator(mode="after")
    def validate_model(self) -> "ZincSettings":
        for mirror_name, mirror_settings in self.mirrors.items():
            # Check that source peer exists
            if mirror_settings.peers.source not in self.peers:
                raise ValueError(
                    f"mirrors.{mirror_name}.peers.source references unknown peer '{mirror_settings.peers.source}'."
                )

            # Check that destination peer exists
            if mirror_settings.peers.destination not in self.peers:
                raise ValueError(
                    f"mirrors.{mirror_name}.peers.destination references unknown peer '{mirror_settings.peers.destination}'."
                )

            source_peer = self.peers[mirror_settings.peers.source]
            destination_peer = self.peers[mirror_settings.peers.destination]

            for table in mirror_settings.tables:
                source_table_identifier = table_identifier_from_string(
                    source_peer.type, table.source
                )
                destination_table_identifier = table_identifier_from_string(
                    destination_peer.type, table.destination
                )

                # Check that source and destination table identifiers are fully qualified
                if (
                    not source_table_identifier.is_fully_qualified()
                    or not destination_table_identifier.is_fully_qualified()
                ):
                    raise ValueError(
                        f"mirrors.{mirror_name}.tables source and destination table identifiers must be fully qualified."
                    )

                # Check that table indexes are supported by adapter
                if table.indexes and destination_peer.type != AdapterType.POSTGRES:
                    raise ValueError(
                        f"Table indexes are not supported by '{destination_peer.type}' adapter."
                    )

        return self

    def model_post_init(self, __context: Any) -> None:
        for mirror_settings in self.mirrors.values():
            destination_peer = self.peers[mirror_settings.peers.destination]

            for table in mirror_settings.tables:
                for index in table.indexes:
                    if not index.name:
                        index.name = index.generate_index_name(
                            destination_peer.type, table.destination, index.columns
                        )
