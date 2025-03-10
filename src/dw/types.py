from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Any, Dict, List, Optional


class AdapterType(StrEnum):
    DUCKDB = "duckdb"
    POSTGRES = "postgres"


class TableIndexType(StrEnum):
    BTREE = "btree"


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


class DuckDBSettings(BaseModel):
    database: Path | str
    schema_: str = Field(default="main", serialization_alias="schema")
    extensions: Optional[List[str]] = []
    settings: Optional[Dict[str, Any]] = {}


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
    type: TableIndexType = Field(default=TableIndexType.BTREE)

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
                    f"mirrors.{mirror_name}.peers.source references unknown peer '{mirror_settings.peers.source}'"
                )

            # Check that destination peer exists
            if mirror_settings.peers.destination not in self.peers:
                raise ValueError(
                    f"mirrors.{mirror_name}.peers.destination references unknown peer '{mirror_settings.peers.destination}'"
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
                        f"mirrors.{mirror_name}.tables source and destination table identifiers must be fully qualified"
                    )

                # Check that table indexes are supported by adapter
                if table.indexes and destination_peer.type != AdapterType.POSTGRES:
                    raise ValueError(
                        f"Table indexes are only supported for '{AdapterType.POSTGRES}' adapter"
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
