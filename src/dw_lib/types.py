from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import Any, Dict, List, Optional, TypedDict

import math
import psutil


class AdapterType(StrEnum):
    CLICKHOUSE = "clickhouse"
    DUCKDB = "duckdb"
    POSTGRES = "postgres"


class TableIndexType(StrEnum):
    BTREE = "btree"


class CreateTableStatementOptions(TypedDict):
    schema: Optional[str] = None
    if_not_exists: Optional[bool] = False
    include_autoincrement: Optional[bool] = False
    include_index: Optional[bool] = False
    include_primary_key_constraint: Optional[bool] = False
    include_foreign_key_constraint: Optional[bool] = False
    include_unique_constraint: Optional[bool] = False


class ClickHouseIdentifier:
    @classmethod
    def quote(cls, identifier: str) -> str:
        return f"`{identifier}`"

    @classmethod
    def unquote(cls, identifier: str) -> str:
        return identifier.strip("`")


class ClickHouseTableIdentifier(ClickHouseIdentifier, BaseModel):
    database: Optional[str] = Field(default=None, serialization_alias="database")
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
    database: Optional[str] = Field(default=None, serialization_alias="database")
    schema_: Optional[str] = Field(default=None, serialization_alias="schema")
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

    memory_limit: Optional[str] = calculate_memory_limit(80)
    threads: Optional[int | str] = calculate_threads(100)

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
    secure: Optional[bool] = Field(default=False)
    driver: Optional[str] = Field(default=None)


class DuckDBSettings(BaseSettings):
    database: Path | str
    schema_: str = Field(default="main", serialization_alias="schema")
    extensions: Optional[List[str]] = None
    settings: Optional[DuckDBSystemSettings] = None


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
    meta: Optional[DbtColumnMeta] = None
    name: str


class DbtContract(BaseModel):
    alias_types: bool
    enforced: bool


class DbtDependsOn(BaseModel):
    macros: Optional[List[str]] = None
    nodes: Optional[List[str]] = None


class DbtDocs(BaseModel):
    node_color: Optional[str] = None
    show: bool


class DbtPersistDocs(BaseModel):
    columns: Optional[bool] = None


class DbtTableMeta(BaseModel):
    python_class: str


class DbtTable(BaseModel):
    columns: Optional[List[DbtColumn]] = None
    loaded_at_field: Optional[str] = None
    meta: Optional[DbtTableMeta] = None
    name: str


class DbtBaseResource(BaseModel):
    name: str
    original_file_path: str
    package_name: str
    resource_type: DbtResourceType
    tags: List[str]
    unique_id: str


class DbtModelConfig(BaseModel):
    access: str
    alias: Optional[str] = None
    batch_filter: Optional[str] = None
    batch_size: Optional[int] = None
    column_types: Dict[str, str]
    contract: DbtContract
    database: Optional[str] = None
    docs: DbtDocs
    enabled: bool
    engine: Optional[str] = None
    full_refresh: Optional[bool] = False
    grants: Dict[str, List[str]]
    group: Optional[str] = None
    incremental_strategy: Optional[str] = None
    materialized: str
    meta: Dict[str, str | int | float | bool | None]
    on_configuration_change: str
    on_schema_change: str
    order_by: Optional[str] = None
    packages: List[str]
    persist_docs: DbtPersistDocs
    post_hook: Optional[List[str]] = None
    pre_hook: Optional[List[str]] = None
    quoting: Dict[str, bool]
    range_max: Optional[str] = None
    range_min: Optional[str] = None
    schema_: Optional[str] = Field(default=None, serialization_alias="schema")
    tags: List[str]
    unique_key: Optional[str] = None


class DbtModel(DbtBaseResource):
    alias: str
    config: DbtModelConfig
    depends_on: DbtDependsOn


class DbtSeedConfig(BaseModel):
    alias: Optional[str] = None
    column_types: Dict[str, str]
    contract: DbtContract
    database: Optional[str] = None
    delimiter: str
    docs: DbtDocs
    enabled: bool
    full_refresh: Optional[bool] = False
    grants: Dict[str, List[str]]
    group: Optional[str] = None
    incremental_strategy: Optional[str] = None
    materialized: str
    meta: Dict[str, str | int | float | bool | None]
    on_configuration_change: str
    on_schema_change: str
    packages: List[str]
    persist_docs: DbtPersistDocs
    post_hook: Optional[List[str]] = None
    pre_hook: Optional[List[str]] = None
    quote_columns: Optional[bool] = None
    quoting: Dict[str, bool]
    schema_: Optional[str] = Field(default=None, serialization_alias="schema")
    tags: List[str]
    unique_key: Optional[str] = None


class DbtSeed(DbtBaseResource):
    alias: str
    config: DbtSeedConfig
    depends_on: DbtDependsOn


class DbtSourceConfig(BaseModel):
    enabled: bool


class DbtSource(DbtBaseResource):
    config: DbtSourceConfig
    original_config: Optional[DbtTable] = None
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
    name: Optional[str] = None
    columns: List[str] = Field(min_length=1)
    type: TableIndexType = TableIndexType.BTREE

    @classmethod
    def generate_index_name(cls, adapter_type: AdapterType, table: str, columns: List[str]) -> str:
        table_identifier = table_identifier_from_string(adapter_type, table)
        return f"ix_{table_identifier.table}_{'_'.join(columns)}"


class ZincMirrorTableSettings(BaseModel):
    source: str
    destination: str
    query: Optional[str] = None
    indexes: Optional[List[ZincMirrorTableIndexSettings]] = []

    @classmethod
    def generate_query(cls, source: str) -> str:
        return f"select * from {source};"

    def model_post_init(self, __context: Any) -> None:
        if not self.query:
            self.query = self.generate_query(self.source)


class ZincMirrorSettings(BaseModel):
    peers: ZincMirrorPeersSettings
    tables: List[ZincMirrorTableSettings] = Field(min_length=1)


ZincPeersSettings = Dict[str, ZincDuckDBPeerSettings | ZincPostgresPeerSettings]
ZincMirrorsSettings = Dict[str, ZincMirrorSettings]


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
