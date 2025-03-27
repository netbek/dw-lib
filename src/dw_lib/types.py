from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Any, Dict, List, Optional

import math
import psutil


class AdapterType(StrEnum):
    CLICKHOUSE = "clickhouse"
    DUCKDB = "duckdb"
    POSTGRES = "postgres"


class TableIndexType(StrEnum):
    BTREE = "btree"


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


class ClickHouseSettings(BaseModel):
    host: str
    http_port: int
    tcp_port: int
    username: str
    password: str
    database: str
    secure: Optional[bool] = Field(default=False)
    driver: Optional[str] = Field(default=None)


class DuckDBSettings(BaseModel):
    database: Path | str
    schema_: str = Field(default="main", serialization_alias="schema")
    extensions: Optional[List[str]] = None
    settings: Optional[DuckDBSystemSettings] = None


class PostgresSettings(BaseModel):
    host: str
    port: int
    username: str
    password: str
    database: str
    schema_: str = Field(default="public", serialization_alias="schema")


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
