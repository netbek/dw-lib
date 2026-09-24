from .database import (
    ClickHouseAdapter,
    ClickHouseRelation,
    ClickHouseSettings,
    PostgresAdapter,
    PostgresRelation,
    PostgresSettings,
)
from .exceptions import (
    ConfigFileNotFoundException,
    CreateMirrorException,
    CreatePeerException,
    DropMirrorException,
    DropPeerException,
    EmptyConfigException,
    GetDynamicSettingsException,
    GetMirrorStatusException,
    GetPeerInfoException,
    GetPeerTypeException,
    ListMirrorsException,
    ListPeersException,
    MirrorExistsException,
    MirrorNotFoundException,
    MirrorTimeoutException,
    PauseMirrorException,
    PeerExistsException,
    PeerNotFoundException,
    ResumeMirrorException,
    ResyncMirrorException,
    SetDynamicSettingsException,
    TableNotFoundException,
    UnsupportedAdapterException,
)
from .types import HttpUrl
from .utils.filesystem import find_up
from .utils.template import render_template
from functools import cached_property
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from rich.console import Console
from rich.table import Table
from ruamel.yaml import YAML
from sqlalchemy import text
from sqlglot.dialects.dialect import Dialects
from typing import Any, Literal, Self

import datetime
import os
import pydash
import requests
import time

# Timeout in seconds for individual HTTP requests to the PeerDB API
REQUEST_TIMEOUT = 5

# Timeout in seconds for waiting on long-running PeerDB operations (e.g. mirror state changes)
OPERATION_TIMEOUT = 15

PEERDB_SOURCE_PEER = "source"
PEERDB_DESTINATION_PEER = "destination"

# https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L289
DIALECT_TO_PEERDB_TYPE_MAP = {
    Dialects.POSTGRES: 3,
    Dialects.CLICKHOUSE: 8,
}


class FlowStatus:
    """
    PeerDB flow status codes.

    Mirrors the `FlowStatus` enum in the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/flow.proto#L586
    """

    STATUS_UNKNOWN = 0
    STATUS_RUNNING = 1
    STATUS_PAUSED = 2
    STATUS_PAUSING = 3
    STATUS_SETUP = 4
    STATUS_SNAPSHOT = 5
    STATUS_TERMINATING = 6
    STATUS_TERMINATED = 7
    STATUS_COMPLETED = 8
    STATUS_RESYNC = 9
    STATUS_FAILED = 10
    STATUS_MODIFYING = 11


LITERAL_FLOW_STATUS_LABELS = {
    attr: attr.removeprefix("STATUS_").replace("_", " ").title()
    for attr in dir(FlowStatus)
    if attr.startswith("STATUS_")
}


# https://www.postgresql.org/docs/17/view-pg-replication-slots.html
class ListReplicationSlotsItem(BaseModel):
    """
    Replication slot details for the source Postgres database.

    Combines `pg_replication_slots`, `pg_control_checkpoint`,
    `pg_stat_activity`, `pg_stat_replication`, and (on Postgres 16+)
    `pg_stat_replication_slots` with computed lag columns.

    See:
        https://www.postgresql.org/docs/17/view-pg-replication-slots.html
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/connectors/postgres/client.go#L295

    Attributes:
        slot_name: Name of the replication slot.
        redo_lsn: Redo LSN from `pg_control_checkpoint()`.
        restart_lsn: Oldest WAL still required by the slot.
        current_lsn: Current WAL LSN at query time.
        active: Whether the slot is actively streaming.
        inactive_since: When the slot became inactive, if ever.
        lag_mb: Approximate lag from `restart_lsn` to current LSN in MB.
        confirmed_flush_lsn: Last LSN confirmed flushed by the consumer.
        sent_lsn: Last LSN sent on the walsender, if active.
        restart_to_confirmed_mb: MB between restart and confirmed-flush LSNs.
        confirmed_to_current_mb: MB between confirmed-flush and current LSNs.
        wal_status: Slot WAL availability (`reserved`, `extended`, `lost`, ...).
        safe_wal_size: Safe WAL size in bytes, if available.
        wait_event_type: Wait event type of the walsender backend, if active.
        wait_event: Wait event of the walsender backend, if active.
        backend_state: State of the walsender backend, if active.
        logical_decoding_work_mem_mb: `logical_decoding_work_mem` in MB.
        stats_reset: Stats reset time as epoch seconds (Postgres 16+).
        spill_txns: Spilled transactions (Postgres 16+).
        spill_count: Spill count (Postgres 16+).
        spill_bytes: Spilled bytes (Postgres 16+).
        failover: Whether the slot is failover-aware.
        synced: Whether the slot is synced to the standby.
    """

    slot_name: str
    redo_lsn: str
    restart_lsn: str | None = None
    current_lsn: str
    active: bool | None = None
    inactive_since: datetime.datetime | None = None
    lag_mb: int | None = None
    confirmed_flush_lsn: str | None = None
    sent_lsn: str | None = None
    restart_to_confirmed_mb: int | None = None
    confirmed_to_current_mb: int | None = None
    wal_status: str
    safe_wal_size: int | None = None
    wait_event_type: str | None = None
    wait_event: str | None = None
    backend_state: str | None = None
    logical_decoding_work_mem_mb: int | None = None
    stats_reset: int | None = None
    spill_txns: int | None = None
    spill_count: int | None = None
    spill_bytes: int | None = None
    failover: bool
    synced: bool


class DynamicSetting(BaseModel):
    """
    A PeerDB dynamic setting.

    Mirrors the `DynamicSetting` message in the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L39

    Attributes:
        name: Setting name.
        default_value: Default value from the server.
        description: Human-readable description from the server.
        value_type: Declared value type (`INT`, `UINT`, `STRING`, `BOOL`).
        apply_mode: When the value takes effect.
        target_for_setting: Peer type the setting applies to.
        value: Current value, if set.
    """

    name: str
    default_value: str = Field(alias="defaultValue")
    description: str
    value_type: Literal["INT", "UINT", "STRING", "BOOL"] = Field(alias="valueType")
    apply_mode: Literal[
        "APPLY_MODE_IMMEDIATE", "APPLY_MODE_AFTER_RESUME", "APPLY_MODE_NEW_MIRROR"
    ] = Field(alias="applyMode")
    target_for_setting: Literal[
        "ALL", "BIGQUERY", "CLICKHOUSE", "POSTGRES", "QUEUES", "SNOWFLAKE"
    ] = Field(alias="targetForSetting")
    value: str | None = None


class GetDynamicSettingsResponse(BaseModel):
    """
    Response listing PeerDB dynamic settings.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L49

    Attributes:
        settings: Dynamic settings returned by the server.
    """

    settings: list[DynamicSetting]


class ClickHouseConfig(BaseModel):
    """
    ClickHouse peer configuration as expected by the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L193

    Attributes:
        host: ClickHouse host.
        port: ClickHouse port.
        user: ClickHouse user.
        password: ClickHouse password.
        database: Default database.
        access_key_id: S3 access key ID for staging.
        secret_access_key: S3 secret access key for staging.
        region: S3 region for staging.
        s3_path: S3 staging path.
        disable_tls: Whether TLS is disabled.
    """

    host: str
    port: int
    user: str
    password: str
    database: str
    access_key_id: str = Field(alias="accessKeyId")
    secret_access_key: str = Field(alias="secretAccessKey")
    region: str
    s3_path: str = Field(alias="s3Path")
    disable_tls: bool = Field(alias="disableTls")
    # TODO Must the TLS fields (certificate, private_key, root_ca) be added?


class ClickHousePeer(BaseModel):
    """
    ClickHouse peer payload for the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L193

    Attributes:
        type: Peer type discriminator, always `CLICKHOUSE`.
        name: Peer name.
        clickhouse_config: ClickHouse connection details.
    """

    type: Literal["CLICKHOUSE"]
    name: str
    clickhouse_config: ClickHouseConfig = Field(alias="clickhouseConfig")


class PostgresConfig(BaseModel):
    """
    Postgres peer configuration as expected by the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L123

    Attributes:
        host: Postgres host.
        port: Postgres port.
        database: Database name.
        user: Database user.
        password: Database password.
    """

    host: str
    port: int
    database: str
    user: str
    password: str


class PostgresPeer(BaseModel):
    """
    Postgres peer payload for the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L123

    Attributes:
        type: Peer type discriminator, always `POSTGRES`.
        name: Peer name.
        postgres_config: Postgres connection details.
    """

    type: Literal["POSTGRES"]
    name: str
    postgres_config: PostgresConfig = Field(alias="postgresConfig")


class PeerInfoResponse(BaseModel):
    """
    Peer details with the live PeerDB version.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L265
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/peer_data.go#L46

    Attributes:
        peer: ClickHouse or Postgres peer payload.
        version: Live peer version reported by the server.
    """

    peer: ClickHousePeer | PostgresPeer
    version: str


class PeerTypeResponse(BaseModel):
    """
    Peer type name reported by the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L270
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/peer_data.go#L87

    Attributes:
        peer_type: Peer type string (e.g. `POSTGRES`, `CLICKHOUSE`).
    """

    peer_type: str = Field(alias="peerType")


class PeerListItem(BaseModel):
    """
    Single peer entry from the peer list API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L274

    Attributes:
        name: Peer name.
        type: Peer type string.
    """

    name: str
    type: str


class ListPeersResponse(BaseModel):
    """
    Peer list split into source, destination, and combined items.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L279
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/peer_data.go#L106

    Attributes:
        destination_items: Destination peers.
        items: All peers.
        source_items: Source peers.
    """

    destination_items: list[PeerListItem] = Field(alias="destinationItems")
    items: list[PeerListItem]
    source_items: list[PeerListItem] = Field(alias="sourceItems")


class RawCreatePeerResponse(BaseModel):
    """
    Raw create-peer response from the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L98
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L606

    Attributes:
        message: Server message.
        status: Creation status (`VALIDATION_UNKNOWN`, `CREATED`, `FAILED`).
    """

    message: str
    status: Literal["VALIDATION_UNKNOWN", "CREATED", "FAILED"]


class CreatePeerResponse(BaseModel):
    """
    High-level result of a create-peer operation.

    Attributes:
        message: Human-readable result (created, kept, or replaced).
        response: Raw API response, if the API was called.
    """

    message: str
    response: RawCreatePeerResponse | None = None


class DropPeerResponse(BaseModel):
    """
    High-level result of a drop-peer operation.

    Attributes:
        message: Human-readable result.
    """

    message: str


class RawCreateMirrorResponse(BaseModel):
    """
    Raw create-mirror response from the PeerDB API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L12

    Attributes:
        workflow_id: Temporal workflow ID for the new mirror.
    """

    workflow_id: str = Field(alias="workflowId")


class CreateMirrorResponse(BaseModel):
    """
    High-level result of a create-mirror operation.

    Attributes:
        message: Human-readable result (created, kept, or replaced).
        response: Raw API response, if the API was called.
    """

    message: str
    response: RawCreateMirrorResponse | None = None


class DropMirrorResponse(BaseModel):
    """
    High-level result of a drop-mirror operation.

    Attributes:
        message: Human-readable result.
    """

    message: str


class ResyncMirrorResponse(BaseModel):
    """
    High-level result of a resync-mirror operation.

    Attributes:
        message: Human-readable result.
    """

    message: str


class PauseMirrorResponse(BaseModel):
    """
    High-level result of a pause-mirror operation.

    Attributes:
        message: Human-readable result.
    """

    message: str


class ResumeMirrorResponse(BaseModel):
    """
    High-level result of a resume-mirror operation.

    Attributes:
        message: Human-readable result.
    """

    message: str


class MirrorStatusResponse(BaseModel):
    """
    Current status of a mirror.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L362
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/mirror_status.go#L68
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/flow.proto#L586

    Attributes:
        created_at: When the mirror workflow was created.
        current_flow_state: Flow status enum value (e.g. `STATUS_RUNNING`).
        flow_job_name: Mirror (flow job) name.
    """

    created_at: datetime.datetime = Field(alias="createdAt")
    current_flow_state: Literal[
        "STATUS_UNKNOWN",
        "STATUS_RUNNING",
        "STATUS_PAUSED",
        "STATUS_PAUSING",
        "STATUS_SETUP",
        "STATUS_SNAPSHOT",
        "STATUS_TERMINATING",
        "STATUS_TERMINATED",
        "STATUS_COMPLETED",
        "STATUS_RESYNC",
        "STATUS_FAILED",
        "STATUS_MODIFYING",
    ] = Field(alias="currentFlowState")
    flow_job_name: str = Field(alias="flowJobName")


class ListMirrorsItem(BaseModel):
    """
    Single mirror entry from the mirror list API.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L447
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/mirror_status.go#L26

    Attributes:
        id: Mirror ID.
        workflow_id: Temporal workflow ID.
        name: Mirror (flow job) name.
        source_name: Source peer name.
        source_type: Source peer type.
        destination_name: Destination peer name.
        destination_type: Destination peer type.
        created_at: When the mirror was created.
        is_cdc: Whether the mirror is a CDC mirror.
        replication_slot: Replication slot details, when enriched locally.
    """

    id: str
    workflow_id: str = Field(alias="workflowId")
    name: str
    source_name: str = Field(alias="sourceName")
    source_type: str = Field(alias="sourceType")
    destination_name: str = Field(alias="destinationName")
    destination_type: str = Field(alias="destinationType")
    created_at: datetime.datetime = Field(alias="createdAt")
    is_cdc: bool = Field(alias="isCdc")
    replication_slot: ListReplicationSlotsItem | None = None


class ListMirrorsResponse(BaseModel):
    """
    Response listing mirrors.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L460

    Attributes:
        mirrors: Mirrors sorted by name by this library.
    """

    mirrors: list[ListMirrorsItem]


class ListPublicationsItem(BaseModel):
    """
    A Postgres publication-table pair.

    Attributes:
        publication_name: Publication name (may be empty for PeerDB-managed).
        relation: Source table relation.
    """

    publication_name: str
    relation: PostgresRelation


class ConfigSetting(BaseModel):
    """
    A dynamic setting from the local YAML config.

    Attributes:
        name: Setting name.
        value: Setting value.
    """

    name: str
    value: str


class ConfigPeerAdapterClickHouse(BaseModel):
    """
    Local adapter config for a ClickHouse peer.

    Attributes:
        type: Adapter type string.
        settings: ClickHouse connection settings.
    """

    type: str
    settings: ClickHouseSettings


class ConfigPeerPeerDBClickHouseConfig(BaseModel):
    """
    PeerDB-side ClickHouse connection config from local YAML.

    Attributes:
        host: ClickHouse host.
        port: ClickHouse port.
        user: ClickHouse user.
        password: ClickHouse password.
        database: Database name.
        disable_tls: Whether TLS is disabled.
        certificate: TLS certificate, required when TLS is enabled.
        private_key: TLS private key, required when TLS is enabled.
        root_ca: TLS root CA, required when TLS is enabled.
    """

    host: str
    port: int
    user: str
    password: str
    database: str
    disable_tls: bool = True
    certificate: str | None = None
    private_key: str | None = None
    root_ca: str | None = None

    @model_validator(mode="after")
    def validate_tls_fields(self) -> Self:
        """
        Validate TLS field combinations.

        Returns:
            Self: This instance when the TLS configuration is consistent.

        Raises:
            ValueError: If TLS fields are provided while `disable_tls` is True,
                or missing while `disable_tls` is False.
        """
        tls_fields = [self.certificate, self.private_key, self.root_ca]

        if self.disable_tls:
            if any(tls_fields):
                raise ValueError(
                    "certificate, private_key and root_ca must not be provided because disable_tls=True"
                )
        else:
            if not all(tls_fields):
                raise ValueError(
                    "certificate, private_key and root_ca must be provided because disable_tls=False"
                )

        return self


class ConfigPeerPeerDBClickHouse(BaseModel):
    """
    PeerDB API payload wrapper for a ClickHouse peer.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L289

    Attributes:
        type: PeerDB numeric type for ClickHouse (8).
        clickhouse_config: ClickHouse connection details.
    """

    type: Literal[8]
    clickhouse_config: ConfigPeerPeerDBClickHouseConfig


class ConfigPeerClickHouse(BaseModel):
    """
    Combined local ClickHouse peer entry.

    Attributes:
        name: Peer name.
        adapter: Local database adapter config.
        peerdb: PeerDB API peer config.
    """

    name: str
    adapter: ConfigPeerAdapterClickHouse
    peerdb: ConfigPeerPeerDBClickHouse


class ConfigPeerAdapterPostgres(BaseModel):
    """
    Local adapter config for a Postgres peer.

    Attributes:
        type: Adapter type string.
        settings: Postgres connection settings.
    """

    type: str
    settings: PostgresSettings


class SSHConfig(BaseModel):
    """
    SSH tunnel config for a Postgres peer.

    Attributes:
        host: SSH host.
        port: SSH port.
        user: SSH user.
        private_key: SSH private key.
    """

    host: str
    port: int
    user: str
    private_key: str


class ConfigPeerPeerDBPostgresConfig(BaseModel):
    """
    PeerDB-side Postgres connection config from local YAML.

    Attributes:
        host: Postgres host.
        port: Postgres port.
        database: Database name.
        user: Database user.
        password: Database password.
        ssh_config: Optional SSH tunnel config.
    """

    host: str
    port: int
    database: str
    user: str
    password: str
    ssh_config: SSHConfig | None = None


class ConfigPeerPeerDBPostgres(BaseModel):
    """
    PeerDB API payload wrapper for a Postgres peer.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L289

    Attributes:
        type: PeerDB numeric type for Postgres (3).
        postgres_config: Postgres connection details.
    """

    type: Literal[3]
    postgres_config: ConfigPeerPeerDBPostgresConfig


class ConfigPeerPostgres(BaseModel):
    """
    Combined local Postgres peer entry.

    Attributes:
        name: Peer name.
        adapter: Local database adapter config.
        peerdb: PeerDB API peer config.
    """

    name: str
    adapter: ConfigPeerAdapterPostgres
    peerdb: ConfigPeerPeerDBPostgres


class ConfigMirrorTableMapping(BaseModel):
    """
    Source-to-destination table mapping for a mirror.

    Attributes:
        source_table_identifier: Source `schema.table` identifier.
        destination_table_identifier: Destination `schema.table` identifier.
        exclude: Columns to exclude from replication, if any.
    """

    source_table_identifier: str
    destination_table_identifier: str
    exclude: list[str] | None = None


class ConfigMirror(BaseModel):
    """
    Mirror definition from the local YAML config.

    Mirrors `FlowConnectionConfigs` fields used by `CreateCDCFlow`.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L12
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L158

    Attributes:
        flow_job_name: Mirror (flow job) name.
        source_name: Source peer name.
        destination_name: Destination peer name.
        table_mappings: Tables to replicate.
        do_initial_snapshot: Whether to take an initial snapshot.
        idle_timeout_seconds: Idle timeout in seconds.
        initial_snapshot_only: Whether to run only the initial snapshot.
        max_batch_size: Maximum batch size.
        publication_name: Publication name (empty lets PeerDB manage it).
        resync: Whether to resync on creation.
        snapshot_max_parallel_workers: Snapshot parallel workers.
        snapshot_num_rows_per_partition: Snapshot rows per partition.
        snapshot_num_tables_in_parallel: Snapshot tables in parallel.
        soft_delete_col_name: Soft-delete marker column name.
        synced_at_col_name: Sync timestamp column name.
    """

    flow_job_name: str
    source_name: str
    destination_name: str
    table_mappings: list[ConfigMirrorTableMapping]
    do_initial_snapshot: bool | None = False
    idle_timeout_seconds: int | None = 60
    initial_snapshot_only: bool | None = False
    max_batch_size: int | None = 1000000
    publication_name: str | None = ""
    resync: bool | None = False
    snapshot_max_parallel_workers: int | None = 4
    snapshot_num_rows_per_partition: int | None = 1000000
    snapshot_num_tables_in_parallel: int | None = 1
    soft_delete_col_name: str | None = "_peerdb_is_deleted"
    synced_at_col_name: str | None = "_peerdb_synced_at"


class Config(BaseModel):
    """
    Parsed PeerDB YAML config.

    Attributes:
        peerdb_ui_url: PeerDB UI base URL; `peerdb_api_url` appends `api`.
        operation_timeout: Timeout in seconds for polling operations.
        settings: Dynamic settings from config.
        peers: Configured peers.
        mirrors: Configured mirrors.
    """

    peerdb_ui_url: HttpUrl
    operation_timeout: int = Field(default=OPERATION_TIMEOUT, ge=1)
    settings: list[ConfigSetting]
    peers: list[ConfigPeerClickHouse | ConfigPeerPostgres]
    mirrors: list[ConfigMirror]

    @property
    def peerdb_api_url(self) -> HttpUrl:
        """
        Return the PeerDB API base URL.

        Returns:
            HttpUrl: `peerdb_ui_url` joined with `api`.
        """
        return self.peerdb_ui_url.join("api")


class PeerDB:
    """
    Client for the PeerDB API and local PeerDB YAML config.

    Wraps PeerDB `v1` REST endpoints with local config parsing, peer/mirror
    lifecycle helpers, and source-database introspection.

    See:
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/api.go
        https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go

    Attributes:
        _config_file: Resolved config file path.
        _headers: Default JSON headers for API requests.
        _console: Rich console for status output.
    """

    def __init__(self, config_file: Path | str | None = None) -> None:
        """
        Initialize the PeerDB client.

        Args:
            config_file: Explicit config file path. When None, resolves via
                `find_config_file()`.
        """
        self._config_file = config_file or find_config_file()
        self._headers = {"Content-Type": "application/json"}
        self._console = Console()

    @cached_property
    def config(self) -> Config:
        """
        Parse and return the local PeerDB config.

        Renders the YAML file as a Jinja template, merges `+defaults` blocks
        into sibling peer/mirror entries, and maps adapter settings to PeerDB
        API numeric types (`POSTGRES=3`, `CLICKHOUSE=8`).

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/peers.proto#L289

        Returns:
            Config: Parsed peers, mirrors, settings, and URLs.

        Raises:
            EmptyConfigException: If the rendered YAML file is empty.
            UnsupportedAdapterException: If a peer adapter type is unsupported.
        """

        def process_node(node: dict) -> dict:
            default_keys = [key for key in node if key.startswith("+")]
            defaults = {key.lstrip("+").strip(): node[key] for key in default_keys}

            if defaults:
                for key, value in node.items():
                    if not key.startswith("+"):
                        node[key] = pydash.defaults(value, defaults)

                node = pydash.omit(node, *default_keys)

            return node

        config = render_template(self._config_file)
        yaml = YAML(typ="safe", pure=True)
        config = yaml.load(config)

        if not config:
            raise EmptyConfigException()

        settings = []
        peers = []
        mirrors = []

        if "settings" in config:
            settings = [
                ConfigSetting(name=key, value=value) for key, value in config["settings"].items()
            ]

        if "peers" in config:
            config["peers"] = process_node(config["peers"])

            for key, value in config["peers"].items():
                adapter_config = {
                    "type": value["type"],
                    "settings": value.get("adapter_settings", value["settings"]),
                }

                if value["type"] == Dialects.CLICKHOUSE:
                    disable_tls = value["settings"].get("disable_tls", True)
                    peerdb_config = {
                        "type": DIALECT_TO_PEERDB_TYPE_MAP[value["type"]],
                        "clickhouse_config": {
                            "host": value["settings"]["host"],
                            "port": value["settings"]["port"],
                            "user": value["settings"]["username"],
                            "password": value["settings"]["password"],
                            "database": value["settings"]["database"],
                            "disable_tls": disable_tls,
                        },
                    }

                    if not disable_tls:
                        peerdb_config["clickhouse_config"].update(
                            pydash.pick(value["settings"], "certificate", "private_key", "root_ca")
                        )

                elif value["type"] == Dialects.POSTGRES:
                    if "ssh_config" in value["settings"]:
                        ssh_config = pydash.pick(
                            value["settings"]["ssh_config"], "host", "port", "user", "private_key"
                        )
                    else:
                        ssh_config = None

                    peerdb_config = {
                        "type": DIALECT_TO_PEERDB_TYPE_MAP[value["type"]],
                        "postgres_config": {
                            "host": value["settings"]["host"],
                            "port": value["settings"]["port"],
                            "user": value["settings"]["username"],
                            "password": value["settings"]["password"],
                            "database": value["settings"]["database"],
                            "ssh_config": ssh_config,
                        },
                    }

                else:
                    raise UnsupportedAdapterException(
                        f"Adapter type '{value['type']}' is not supported"
                    )

                peers.append(
                    {
                        "name": key,
                        "adapter": adapter_config,
                        "peerdb": peerdb_config,
                    }
                )

        if "mirrors" in config:
            config["mirrors"] = process_node(config["mirrors"])

            for key in config["mirrors"]:
                config["mirrors"][key]["flow_job_name"] = key

            mirrors = list(config["mirrors"].values())

        return Config(
            peerdb_ui_url=config.get("peerdb_ui_url"),
            operation_timeout=config.get("operation_timeout", OPERATION_TIMEOUT),
            settings=settings,
            peers=peers,
            mirrors=mirrors,
        )

    def can_connect(self) -> bool:
        """
        Check whether the PeerDB API is reachable.

        Sends `GET v1/version`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L823
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/version.go#L10

        Returns:
            bool: True on HTTP success, False on HTTP or connection errors.
        """
        url = self.config.peerdb_api_url.join("v1/version")

        try:
            response = requests.get(str(url), headers=self._headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return True
        except (requests.HTTPError, requests.ConnectionError):
            return False

    def debug(self, echo: bool = False) -> dict[str, dict[str, Any]]:
        """
        Check API, source, and destination connectivity and prerequisites.

        Verifies the PeerDB API, source/destination adapter connections, and
        source Postgres settings (`max_replication_slots >= 4`,
        `max_wal_senders >= 1`, `wal_level = logical`). Optionally prints
        missing/unused publications, peers, mirrors, and replication slots.

        See:
            https://docs.peerdb.io/usecases/Real-time%20CDC/postgres-to-postgres#prerequisites

        Args:
            echo: Whether to print Rich tables to the console.

        Returns:
            dict[str, dict[str, Any]]: Nested `API` / `Source peer` /
                `Destination peer` check results.
        """
        # TODO Add to result: missing publications, unused publications, replication slots
        # TODO Table mappings: check whether the source schema and table exists, check whether the destination schema exists

        def create_message(condition: bool) -> str:
            if condition:
                if echo:
                    return "[green]OK[/green]"
                else:
                    return "OK"
            else:
                if echo:
                    return "[red]Not OK[/red]"
                else:
                    return "Not OK"

        def render_table(data, title: str | None = None) -> Table:
            table = Table(title=title, show_header=True, min_width=80)

            headers = data[0].keys()
            for header in headers:
                table.add_column(header)

            for item in data:
                table.add_row(*[str(value) for value in item.values()])

            return table

        try:
            self.get_settings()
            api_can_connect = True
        except Exception:  # noqa: BLE001
            api_can_connect = False

        source_adapter = self.get_peer_adapter(PEERDB_SOURCE_PEER)
        destination_adapter = self.get_peer_adapter(PEERDB_DESTINATION_PEER)
        source_can_connect = source_adapter.can_connect()
        destination_can_connect = destination_adapter.can_connect()

        # Check settings of source peer
        # https://docs.peerdb.io/usecases/Real-time%20CDC/postgres-to-postgres#prerequisites
        if source_can_connect:
            with source_adapter.create_client() as (_, cur):
                cur.execute("""
                    SELECT
                        current_setting('max_replication_slots')::int,
                        current_setting('max_wal_senders')::int,
                        lower(current_setting('wal_level'));
                    """)
                max_replication_slots, max_wal_senders, wal_level = cur.fetchone()

            max_replication_slots_is_valid = max_replication_slots >= 4
            max_wal_senders_is_valid = max_wal_senders >= 1
            wal_level_is_valid = wal_level == "logical"
        else:
            max_replication_slots_is_valid = False
            max_wal_senders_is_valid = False
            wal_level_is_valid = False

        result = {
            "API": {
                "URL": self.config.peerdb_api_url,
                "Connection test": create_message(api_can_connect),
            },
            "Source peer": {
                "URL": source_adapter.settings.to_sqlalchemy_url(),
                "Connection test": create_message(source_can_connect),
                "max_replication_slots >= 4": create_message(max_replication_slots_is_valid),
                "max_wal_senders >= 1": create_message(max_wal_senders_is_valid),
                "wal_level = logical": create_message(wal_level_is_valid),
            },
            "Destination peer": {
                "URL": destination_adapter.settings.to_sqlalchemy_url(),
                "Connection test": create_message(destination_can_connect),
            },
        }

        if echo:
            for i, item in enumerate(result.items()):
                k1, v1 = item
                self._console.print(f"{'\n' if i > 0 else ''}{k1}:")
                for k2, v2 in v1.items():
                    self._console.print(f"  {k2}: {v2}")

            # Missing publications
            self._console.print()
            missing_publications_data = [
                {
                    "publication": publication.publication_name,
                    "schema": publication.relation.schema_,
                    "table": publication.relation.table,
                }
                for publication in self.list_missing_publications()
            ]
            if missing_publications_data:
                self._console.print(
                    render_table(missing_publications_data, title="Missing publications")
                )
            else:
                self._console.print("Missing publications: [green]OK (None)[/green]")

            # Unused publications
            self._console.print()
            unused_publications_data = [
                {
                    "publication": publication.publication_name,
                    "schema": publication.relation.schema_,
                    "table": publication.relation.table,
                }
                for publication in self.list_unused_publications()
            ]
            if unused_publications_data:
                self._console.print(
                    render_table(unused_publications_data, title="Unused publications")
                )
            else:
                self._console.print("Unused publications: [green]OK (None)[/green]")

            # Peers
            self._console.print()
            peers_data = [peer.model_dump() for peer in self.list_peers().items]
            if peers_data:
                self._console.print(render_table(peers_data, title="Peers"))
            else:
                self._console.print("Peers: None")

            # Mirrors
            self._console.print()
            mirrors_data = []
            mirrors = self.list_mirrors(include_replication_slot=True).mirrors
            for mirror in mirrors:
                status_response = self.get_mirror_status(mirror.name)
                mirror_data = {
                    **mirror.model_dump(),
                    "status": LITERAL_FLOW_STATUS_LABELS.get(
                        status_response.current_flow_state,
                        status_response.current_flow_state,
                    ),
                }
                mirror_data = {
                    **pydash.pick(mirror_data, "name", "created_at", "status"),
                    "replication_slot_name": pydash.get(mirror_data, "replication_slot.slot_name"),
                }
                mirrors_data.append(mirror_data)
            mirrors_data = pydash.order_by(mirrors_data, ["name"])
            if mirrors_data:
                self._console.print(render_table(mirrors_data, title="Mirrors"))
            else:
                self._console.print("Mirrors: None")

            # Replication slots
            self._console.print()
            replication_slots_data = [
                mirror.replication_slot.model_dump(
                    include=[
                        "slot_name",
                        "active",
                        "inactive_since",
                        "redo_lsn",
                        "restart_lsn",
                        "lag_mb",
                        "failover",
                        "synced",
                    ]
                )
                for mirror in mirrors
                if mirror.replication_slot
            ]
            if replication_slots_data:
                self._console.print(render_table(replication_slots_data, title="Replication slots"))
            else:
                has_running_mirror = any(mirror["status"] == "Running" for mirror in mirrors_data)
                if has_running_mirror:
                    self._console.print(
                        "Replication slots: [red]Not OK (no replication slot for mirror in 'Running' state)[/red]"
                    )
                else:
                    self._console.print("Replication slots: None")

        return result

    def get_peer_adapter(self, peer_name: str) -> ClickHouseAdapter | PostgresAdapter:
        """
        Return the database adapter for a configured peer.

        Args:
            peer_name: Peer name as defined in the local config.

        Returns:
            ClickHouseAdapter | PostgresAdapter: Adapter bound to the peer's
                settings.

        Raises:
            PeerNotFoundException: If no peer with `peer_name` is configured.
            UnsupportedAdapterException: If the peer adapter type has no adapter.
        """
        peer = pydash.find(self.config.peers, lambda x: x.name == peer_name)

        if not peer:
            raise PeerNotFoundException(f"Peer '{peer_name}' not found")

        if peer.adapter.type == Dialects.CLICKHOUSE:
            return ClickHouseAdapter(peer.adapter.settings)
        elif peer.adapter.type == Dialects.POSTGRES:
            return PostgresAdapter(peer.adapter.settings)
        else:
            raise UnsupportedAdapterException(f"Peer type '{peer.adapter.type}' has no adapter")

    def get_settings(self) -> GetDynamicSettingsResponse:
        """
        Fetch PeerDB dynamic settings.

        Sends `GET v1/dynamic_settings`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L644
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/settings.go#L17

        Returns:
            GetDynamicSettingsResponse: Settings returned by the server.

        Raises:
            GetDynamicSettingsException: If the request fails.
        """
        url = self.config.peerdb_api_url.join("v1/dynamic_settings")

        try:
            response = requests.get(str(url), headers=self._headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise GetDynamicSettingsException(
                f"Failed to get dynamic settings ({error_message or exc})"
            )

        return GetDynamicSettingsResponse(**response.json())

    def update_settings(self, settings: dict[str, str]) -> None:
        """
        Update PeerDB dynamic settings one by one.

        Sends `POST v1/dynamic_settings` with `{name, value}` per entry.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L650
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/settings.go#L61

        Args:
            settings: Mapping of setting names to new values.

        Raises:
            SetDynamicSettingsException: If any update request fails.
        """
        self._console.print("Updating settings")

        url = self.config.peerdb_api_url.join("v1/dynamic_settings")

        for key, value in settings.items():
            data = {"name": key, "value": value}

            try:
                response = requests.post(
                    str(url), json=data, headers=self._headers, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
            except (requests.HTTPError, requests.ConnectionError) as exc:
                try:
                    error_message = response.json().get("message")
                except Exception:  # noqa: BLE001
                    error_message = None
                raise SetDynamicSettingsException(
                    f"Failed to set {key}={value} ({error_message or exc})"
                )

    def has_peer(self, peer_name: str) -> bool:
        """
        Check whether a peer exists on the server.

        Args:
            peer_name: Peer name to look up.

        Returns:
            bool: True when a peer with `peer_name` is listed.
        """
        response = self.list_peers()
        matched = pydash.find(response.items, lambda x: x.name == peer_name)

        return bool(matched)

    def get_peer_info(self, peer_name: str) -> PeerInfoResponse:
        """
        Fetch peer details and live version.

        Sends `GET v1/peers/info/{peer_name}`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L806
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/peer_data.go#L46

        Args:
            peer_name: Peer name to inspect.

        Returns:
            PeerInfoResponse: Peer payload with live version.

        Raises:
            GetPeerInfoException: If the request fails.
        """
        url = self.config.peerdb_api_url.join(f"v1/peers/info/{peer_name}")

        try:
            response = requests.get(str(url), headers=self._headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise GetPeerInfoException(
                f"Failed to get peer info of '{peer_name}' ({error_message or exc})"
            )

        return PeerInfoResponse(**response.json())

    def get_peer_type(self, peer_name: str) -> PeerTypeResponse:
        """
        Fetch the type string of a peer.

        Sends `GET v1/peers/type/{peer_name}`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L812
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/peer_data.go#L87

        Args:
            peer_name: Peer name to inspect.

        Returns:
            PeerTypeResponse: Peer type reported by the server.

        Raises:
            GetPeerTypeException: If the request fails.
        """
        url = self.config.peerdb_api_url.join(f"v1/peers/type/{peer_name}")

        try:
            response = requests.get(str(url), headers=self._headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise GetPeerTypeException(
                f"Failed to get peer type of '{peer_name}' ({error_message or exc})"
            )

        return PeerTypeResponse(**response.json())

    def create_peer(
        self, peer: dict, if_exists: Literal["fail", "keep", "replace"] = "fail"
    ) -> CreatePeerResponse:
        """
        Create a peer on the server.

        Sends `POST v1/peers/create` with `{peer}` and requires status
        `CREATED`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L598
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L606

        Args:
            peer: Peer payload as built from the local config.
            if_exists: Behavior when the peer already exists: `fail` raises,
                `keep` returns without calling the API, `replace` drops the
                peer with mirrors and destination tables first.

        Returns:
            CreatePeerResponse: Result with created/kept/replaced message.

        Raises:
            PeerExistsException: If the peer exists and `if_exists` is `fail`.
            CreatePeerException: If the request fails or status is not `CREATED`.
        """
        self._console.print(f"Creating peer '{peer['name']}'")

        has_peer = self.has_peer(peer["name"])

        if has_peer:
            if if_exists == "keep":
                return CreatePeerResponse(message=f"Kept peer '{peer['name']}'")
            elif if_exists == "replace":
                self.drop_peer(peer["name"], drop_mirrors=True, drop_destination_tables=True)
            else:
                raise PeerExistsException(f"Peer '{peer['name']}' exists")

        url = self.config.peerdb_api_url.join("v1/peers/create")
        data = {"peer": peer}

        try:
            response = requests.post(
                str(url), json=data, headers=self._headers, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise CreatePeerException(
                f"Failed to create peer '{peer['name']}' ({error_message or exc})"
            )

        deserialized = RawCreatePeerResponse(**response.json())

        if deserialized.status != "CREATED":
            raise CreatePeerException(
                f"Failed to create peer '{peer['name']}' (status: {deserialized.status})"
            )

        if has_peer:
            message = f"Replaced peer '{peer['name']}'"
        else:
            message = f"Created peer '{peer['name']}'"

        return CreatePeerResponse(message=message, response=deserialized)

    def drop_peer(
        self,
        peer_name: str,
        drop_mirrors: bool | None = True,
        drop_destination_tables: bool | None = False,
        if_exists: bool | None = False,
        timeout: int | None = None,
    ) -> DropPeerResponse:
        """
        Drop a peer from the server.

        Optionally drops dependent mirrors first, then sends
        `POST v1/peers/drop` with `{peerName}`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L604
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L631

        Args:
            peer_name: Peer name to drop.
            drop_mirrors: Whether to drop mirrors using this peer first.
            drop_destination_tables: Whether mirror drops also drop
                destination tables.
            if_exists: When True, skip instead of raising if missing.
            timeout: Timeout for dependent mirror drops. Defaults to
                `config.operation_timeout`.

        Returns:
            DropPeerResponse: Result with dropped/skipped message.

        Raises:
            PeerNotFoundException: If the peer is missing and `if_exists` is False.
            DropPeerException: If the drop request fails.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        self._console.print(f"Dropping peer '{peer_name}'")

        if drop_mirrors:
            self.drop_mirrors_of_peer(
                peer_name,
                drop_destination_tables=drop_destination_tables,
                timeout=timeout,
            )

        if not self.has_peer(peer_name):
            if if_exists:
                return DropPeerResponse(
                    message=f"Peer '{peer_name}' not found, skipping because if_exists=True"
                )
            else:
                raise PeerNotFoundException(f"Peer '{peer_name}' not found")

        url = self.config.peerdb_api_url.join("v1/peers/drop")
        data = {"peerName": peer_name}

        try:
            response = requests.post(str(url), json=data, headers=self._headers, timeout=None)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise DropPeerException(f"Failed to drop peer '{peer_name}' ({error_message or exc})")

        return DropPeerResponse(message=f"Dropped peer '{peer_name}'")

    def drop_mirrors_of_peer(
        self,
        peer_name: str,
        drop_destination_tables: bool | None = False,
        timeout: int | None = None,
    ) -> None:
        """
        Drop all mirrors using a peer as source or destination.

        Args:
            peer_name: Peer name to match against mirror endpoints.
            drop_destination_tables: Whether mirror drops also drop
                destination tables.
            timeout: Timeout per mirror drop. Defaults to
                `config.operation_timeout`.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        for mirror in self.list_mirrors().mirrors:
            if mirror.source_name == peer_name or mirror.destination_name == peer_name:
                self.drop_mirror(
                    mirror.name,
                    drop_destination_tables=drop_destination_tables,
                    timeout=timeout,
                )

    def list_peers(self) -> ListPeersResponse:
        """
        List peers from the server.

        Sends `GET v1/peers/list`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L817
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/peer_data.go#L106

        Returns:
            ListPeersResponse: Source, destination, and combined peer items.

        Raises:
            ListPeersException: If the request fails.
        """
        url = self.config.peerdb_api_url.join("v1/peers/list")

        try:
            response = requests.get(str(url), headers=self._headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise ListPeersException(f"Failed to list peers ({error_message or exc})")

        return ListPeersResponse(**response.json())

    def has_mirror(self, flow_job_name: str) -> bool:
        """
        Check whether a mirror exists on the server.

        Args:
            flow_job_name: Mirror (flow job) name to look up.

        Returns:
            bool: True when the mirror status is known, False when the
                mirror is not found.
        """
        try:
            return self.get_mirror_status(flow_job_name).current_flow_state != "STATUS_UNKNOWN"
        except MirrorNotFoundException:
            return False

    def get_mirror_status(self, flow_job_name: str) -> MirrorStatusResponse:
        """
        Fetch the current status of a mirror.

        Sends `POST v1/mirrors/status` with `{flowJobName}`. HTTP 404 means
        the mirror does not exist.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L772
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/mirror_status.go#L68
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/mirror_status.go#L76

        Args:
            flow_job_name: Mirror (flow job) name to inspect.

        Returns:
            MirrorStatusResponse: Status including `current_flow_state`.

        Raises:
            MirrorNotFoundException: If the server returns HTTP 404.
            GetMirrorStatusException: If the request fails otherwise.
        """
        url = self.config.peerdb_api_url.join("v1/mirrors/status")
        data = {"flowJobName": flow_job_name}

        try:
            response = requests.post(
                str(url), json=data, headers=self._headers, timeout=REQUEST_TIMEOUT
            )
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise GetMirrorStatusException(
                f"Failed to get status of mirror '{flow_job_name}' ({error_message or exc})"
            )

        if response.status_code == 200:
            return MirrorStatusResponse(**response.json())
        elif response.status_code == 404:
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")
        else:
            raise GetMirrorStatusException(
                f"Failed to get status of mirror '{flow_job_name}' (HTTP {response.status_code})"
            )

    def wait_for_mirror_status(
        self, flow_job_name: str, target_statuses: set[str], timeout: int | None = None
    ) -> str:
        """
        Poll mirror status until a target status is reached.

        Args:
            flow_job_name: Mirror (flow job) name to poll.
            target_statuses: Statuses that stop polling (e.g.
                `{"STATUS_RUNNING"}`).
            timeout: Polling timeout in seconds. Defaults to
                `config.operation_timeout`.

        Returns:
            str: The reached status value.

        Raises:
            MirrorTimeoutException: If no target status is reached in time.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        current_status = "UNKNOWN"

        for _ in range(timeout):
            current_status = self.get_mirror_status(flow_job_name).current_flow_state

            if current_status in target_statuses:
                return current_status

            time.sleep(1)

        raise MirrorTimeoutException(
            f"Timeout: Mirror '{flow_job_name}' failed to reach status {target_statuses} after {timeout}s (current status: {current_status})"
        )

    def create_mirror(
        self, mirror: dict, if_exists: Literal["fail", "keep", "replace"] = "fail"
    ) -> CreateMirrorResponse:
        """
        Create a CDC mirror on the server.

        Validates that source tables exist, best-effort drops destination
        tables, then sends `POST v1/flows/cdc/create` with
        `{connection_configs}` and requires a `workflowId`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L611
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L158

        Args:
            mirror: Mirror payload as built from the local config.
            if_exists: Behavior when the mirror already exists: `fail` raises,
                `keep` returns without calling the API, `replace` drops the
                mirror with destination tables first.

        Returns:
            CreateMirrorResponse: Result with created/kept/replaced message.

        Raises:
            MirrorExistsException: If the mirror exists and `if_exists` is `fail`.
            PeerNotFoundException: If the source peer is missing from config.
            UnsupportedAdapterException: If the source adapter is not Postgres.
            TableNotFoundException: If a mapped source table is missing.
            CreateMirrorException: If the request fails or lacks `workflowId`.
        """
        self._console.print(f"Creating mirror '{mirror['flow_job_name']}'")

        has_mirror = self.has_mirror(mirror["flow_job_name"])

        if has_mirror:
            if if_exists == "keep":
                return CreateMirrorResponse(message=f"Kept mirror '{mirror['flow_job_name']}'")
            elif if_exists == "replace":
                self.drop_mirror(mirror["flow_job_name"], drop_destination_tables=True)
            else:
                raise MirrorExistsException(f"Mirror '{mirror['flow_job_name']}' exists")

        # Step 1: Check whether the source tables exist
        source_peer = pydash.find(self.config.peers, lambda x: x.name == mirror["source_name"])

        if source_peer is None:
            raise PeerNotFoundException(
                f"Peer '{mirror['source_name']}' not found in PeerDB config"
            )

        if source_peer.adapter.type != Dialects.POSTGRES:
            raise UnsupportedAdapterException(
                f"Adapter type '{source_peer.adapter.type}' is not supported"
            )

        source_adapter = PostgresAdapter(
            PostgresSettings(**source_peer.adapter.settings.model_dump())
        )
        source_tables = source_adapter.list_tables()

        for table_mapping in mirror["table_mappings"]:
            source_relation = PostgresRelation.from_string(table_mapping["source_table_identifier"])
            source_table = pydash.find(
                source_tables,
                lambda x: x.schema == source_relation.schema_ and x.name == source_relation.table,  # noqa: B023
            )

            if source_table is None:
                raise TableNotFoundException(
                    f"Source table '{table_mapping['source_table_identifier']}' not found in database of peer '{source_peer.name}'"
                )

        # Step 2: Drop the destination tables
        try:
            self.drop_destination_tables_of_mirror(mirror["flow_job_name"])
        except (
            MirrorNotFoundException,
            PeerNotFoundException,
            UnsupportedAdapterException,
            TableNotFoundException,
        ) as exc:
            self._console.print(f"Skipping drop of destination tables because of {exc}")

        # Step 3: Create the mirror
        url = self.config.peerdb_api_url.join("v1/flows/cdc/create")
        data = {"connection_configs": mirror}

        try:
            response = requests.post(
                str(url), json=data, headers=self._headers, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise CreateMirrorException(
                f"Failed to create mirror '{mirror['flow_job_name']}' ({error_message or exc})"
            )

        workflow_id = response.json().get("workflowId")

        if not workflow_id:
            raise CreateMirrorException(
                f"Failed to create mirror '{mirror['flow_job_name']}' (HTTP {response.status_code})"
            )

        deserialized = RawCreateMirrorResponse(**response.json())

        if has_mirror:
            message = f"Replaced mirror '{mirror['flow_job_name']}'"
        else:
            message = f"Created mirror '{mirror['flow_job_name']}'"

        return CreateMirrorResponse(message=message, response=deserialized)

    def drop_mirror(
        self,
        flow_job_name: str,
        drop_destination_tables: bool | None = False,
        if_exists: bool | None = False,
        timeout: int | None = None,
    ) -> DropMirrorResponse:
        """
        Drop a mirror and wait until it disappears.

        Sends `POST v1/mirrors/state_change` with `STATUS_TERMINATING`,
        `dropMirrorStats=True`, and `skipDestinationDrop=False`, then polls
        until `has_mirror()` is False.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L765
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L430

        Args:
            flow_job_name: Mirror (flow job) name to drop.
            drop_destination_tables: Whether to also drop destination tables
                via `drop_destination_tables_of_mirror()`.
            if_exists: When True, skip instead of raising if missing.
            timeout: Polling timeout in seconds. Defaults to
                `config.operation_timeout`.

        Returns:
            DropMirrorResponse: Result with dropped/skipped message.

        Raises:
            MirrorNotFoundException: If missing and `if_exists` is False.
            DropMirrorException: If the state-change request fails.
            MirrorTimeoutException: If the mirror still exists after timeout.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        self._console.print(f"Dropping mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            if if_exists:
                return DropMirrorResponse(
                    message=f"Mirror '{flow_job_name}' not found, skipping because if_exists=True"
                )
            else:
                raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        url = self.config.peerdb_api_url.join("v1/mirrors/state_change")
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": FlowStatus.STATUS_TERMINATING,
            "dropMirrorStats": True,
            # SkipDestinationDrop only controls whether PeerDB cleans up its own internal objects
            # (e.g. the raw table) at the destination. It never drops the user's destination
            # tables; those are only dropped when drop_destination_tables = True.
            "skipDestinationDrop": False,
        }

        try:
            response = requests.post(str(url), json=data, headers=self._headers, timeout=None)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise DropMirrorException(
                f"Failed to drop mirror '{flow_job_name}' ({error_message or exc})"
            )

        for _ in range(timeout):
            if not self.has_mirror(flow_job_name):
                break
            time.sleep(1)
        else:
            raise MirrorTimeoutException(
                f"Failed to drop mirror '{flow_job_name}' after {timeout}s"
            )

        if drop_destination_tables:
            try:
                self.drop_destination_tables_of_mirror(flow_job_name)
            except (
                MirrorNotFoundException,
                PeerNotFoundException,
                UnsupportedAdapterException,
                TableNotFoundException,
            ) as exc:
                self._console.print(f"Skipping drop of destination tables because of {exc}")

        return DropMirrorResponse(message=f"Dropped mirror '{flow_job_name}'")

    def resync_mirror(
        self, flow_job_name: str, if_exists: bool | None = False, timeout: int | None = None
    ) -> ResyncMirrorResponse:
        """
        Request a resync of a mirror and wait for resync state.

        Sends `POST v1/mirrors/state_change` with `STATUS_RESYNC` and
        `dropMirrorStats=True`.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L765
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L430
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L506

        Args:
            flow_job_name: Mirror (flow job) name to resync.
            if_exists: When True, skip instead of raising if missing.
            timeout: Wait timeout in seconds. Defaults to
                `config.operation_timeout`.

        Returns:
            ResyncMirrorResponse: Result with initiated/skipped message.

        Raises:
            MirrorNotFoundException: If missing and `if_exists` is False.
            ResyncMirrorException: If the state-change request fails.
            MirrorTimeoutException: If `STATUS_RESYNC` is not reached in time.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        self._console.print(f"Resyncing mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            if if_exists:
                return ResyncMirrorResponse(
                    message=f"Mirror '{flow_job_name}' not found, skipping because if_exists=True"
                )
            else:
                raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        url = self.config.peerdb_api_url.join("v1/mirrors/state_change")
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": FlowStatus.STATUS_RESYNC,
            "dropMirrorStats": True,
        }

        try:
            response = requests.post(str(url), json=data, headers=self._headers, timeout=None)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise ResyncMirrorException(
                f"Failed to resync mirror '{flow_job_name}' ({error_message or exc})"
            )

        self.wait_for_mirror_status(flow_job_name, {"STATUS_RESYNC"}, timeout=timeout)

        return ResyncMirrorResponse(
            message=f"Resync of mirror '{flow_job_name}' has been initiated"
        )

    def pause_mirror(self, flow_job_name: str, timeout: int | None = None) -> PauseMirrorResponse:
        """
        Pause a running mirror and wait for paused state.

        Only sends `POST v1/mirrors/state_change` with `STATUS_PAUSED` when
        the current status is `STATUS_RUNNING`; otherwise returns a no-op
        message.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L765
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L430
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L490

        Args:
            flow_job_name: Mirror (flow job) name to pause.
            timeout: Wait timeout in seconds. Defaults to
                `config.operation_timeout`.

        Returns:
            PauseMirrorResponse: Result with paused or not-pausing message.

        Raises:
            MirrorNotFoundException: If the mirror does not exist.
            PauseMirrorException: If the state-change request fails.
            MirrorTimeoutException: If `STATUS_PAUSED` is not reached in time.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        self._console.print(f"Pausing mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        current_flow_state = self.get_mirror_status(flow_job_name).current_flow_state
        if current_flow_state not in {"STATUS_RUNNING"}:
            return PauseMirrorResponse(
                message=f"Not pausing mirror '{flow_job_name}' because its status is '{current_flow_state}'"
            )

        url = self.config.peerdb_api_url.join("v1/mirrors/state_change")
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": "STATUS_PAUSED",
        }

        try:
            response = requests.post(str(url), json=data, headers=self._headers, timeout=None)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise PauseMirrorException(
                f"Failed to pause mirror '{flow_job_name}' ({error_message or exc})"
            )

        self.wait_for_mirror_status(flow_job_name, {"STATUS_PAUSED"}, timeout=timeout)

        return PauseMirrorResponse(message=f"Paused mirror '{flow_job_name}'")

    def resume_mirror(self, flow_job_name: str, timeout: int | None = None) -> ResumeMirrorResponse:
        """
        Resume a paused mirror and wait for running state.

        Only sends `POST v1/mirrors/state_change` with `STATUS_RUNNING` when
        the current status is `STATUS_PAUSED` or `STATUS_PAUSING`; otherwise
        returns a no-op message.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L765
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L430
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/handler.go#L498

        Args:
            flow_job_name: Mirror (flow job) name to resume.
            timeout: Wait timeout in seconds. Defaults to
                `config.operation_timeout`.

        Returns:
            ResumeMirrorResponse: Result with resumed or not-resuming message.

        Raises:
            MirrorNotFoundException: If the mirror does not exist.
            ResumeMirrorException: If the state-change request fails.
            MirrorTimeoutException: If `STATUS_RUNNING` is not reached in time.
        """
        if timeout is None:
            timeout = self.config.operation_timeout

        self._console.print(f"Resuming mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        current_flow_state = self.get_mirror_status(flow_job_name).current_flow_state
        if current_flow_state not in {"STATUS_PAUSED", "STATUS_PAUSING"}:
            return ResumeMirrorResponse(
                message=f"Not resuming mirror '{flow_job_name}' because its status is '{current_flow_state}'"
            )

        url = self.config.peerdb_api_url.join("v1/mirrors/state_change")
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": "STATUS_RUNNING",
        }

        try:
            response = requests.post(str(url), json=data, headers=self._headers, timeout=None)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise ResumeMirrorException(
                f"Failed to resume mirror '{flow_job_name}' ({error_message or exc})"
            )

        self.wait_for_mirror_status(flow_job_name, {"STATUS_RUNNING"}, timeout=timeout)

        return ResumeMirrorResponse(message=f"Resumed mirror '{flow_job_name}'")

    def drop_destination_tables_of_mirror(self, flow_job_name: str) -> None:
        """
        Drop destination tables for a mirror defined in local config.

        Args:
            flow_job_name: Mirror (flow job) name to look up in local config.

        Raises:
            MirrorNotFoundException: If the mirror is missing from config.
            PeerNotFoundException: If the destination peer is missing from config.
            UnsupportedAdapterException: If the destination adapter is unsupported.
        """
        mirror = pydash.find(self.config.mirrors, lambda x: x.flow_job_name == flow_job_name)

        if mirror is None:
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        destination_peer = pydash.find(
            self.config.peers, lambda x: x.name == mirror.destination_name
        )

        if destination_peer is None:
            raise PeerNotFoundException(f"Peer '{mirror.destination_name}' not found")

        if destination_peer.adapter.type == Dialects.CLICKHOUSE:
            adapter_class = ClickHouseAdapter
            settings_class = ClickHouseSettings
            relation_class = ClickHouseRelation
        elif destination_peer.adapter.type == Dialects.POSTGRES:
            adapter_class = PostgresAdapter
            settings_class = PostgresSettings
            relation_class = PostgresRelation
        else:
            raise UnsupportedAdapterException(
                f"Adapter type '{destination_peer.adapter.type}' is not supported"
            )

        destination_adapter = adapter_class(
            settings_class(**destination_peer.adapter.settings.model_dump())
        )
        destination_relations = [
            relation_class.from_string(table_mapping.destination_table_identifier)
            for table_mapping in mirror.table_mappings
        ]

        for relation in destination_relations:
            destination_adapter.drop_table(**relation.model_dump(by_alias=True), if_exists=True)

    def list_mirrors(self, include_replication_slot: bool = False) -> ListMirrorsResponse:
        """
        List mirrors from the server, sorted by name.

        Sends `GET v1/mirrors/list`. When `include_replication_slot` is True,
        each mirror is enriched with the `peerflow_slot_{mirror}` replication
        slot from the source database.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/route.proto#L753
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/cmd/mirror_status.go#L26
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/connectors/postgres/client.go#L888

        Args:
            include_replication_slot: Whether to attach replication slot details.

        Returns:
            ListMirrorsResponse: Mirrors sorted by name.

        Raises:
            ListMirrorsException: If the request fails.
        """
        url = self.config.peerdb_api_url.join("v1/mirrors/list")

        try:
            response = requests.get(str(url), headers=self._headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            try:
                error_message = response.json().get("message")
            except Exception:  # noqa: BLE001
                error_message = None
            raise ListMirrorsException(f"Failed to list mirrors ({error_message or exc})")

        mirrors = pydash.sort_by(response.json()["mirrors"], "name")

        if include_replication_slot:
            replication_slots = self.list_replication_slots()
            for mirror in mirrors:
                replication_slot_name = f"peerflow_slot_{mirror['name']}"
                replication_slot = pydash.find(
                    replication_slots,
                    lambda x: x.slot_name == replication_slot_name,  # noqa: B023
                )
                mirror["replication_slot"] = replication_slot

        return ListMirrorsResponse(mirrors=mirrors)

    def list_expected_publications(self) -> list[ListPublicationsItem]:
        """
        List publication-table pairs expected from local config.

        Returns:
            list[ListPublicationsItem]: One item per mirror table mapping with
                the mirror's `publication_name`.
        """
        data = []
        for mirror in self.config.mirrors:
            for table_mapping in mirror.table_mappings:
                relation = PostgresRelation.from_string(table_mapping.source_table_identifier)
                data.append(
                    ListPublicationsItem(
                        publication_name=mirror.publication_name, relation=relation
                    )
                )

        return data

    def list_actual_publications(self) -> list[ListPublicationsItem]:
        """
        List publication-table pairs present in the source database.

        Queries `pg_publication_tables` on the `source` peer.

        Returns:
            list[ListPublicationsItem]: Ordered publication-table pairs.
        """
        source_adapter = self.get_peer_adapter(PEERDB_SOURCE_PEER)
        data = []
        with source_adapter.create_session() as session:
            query = """
            SELECT pubname, schemaname, tablename
            FROM pg_publication_tables
            ORDER BY pubname, schemaname, tablename
            """
            result = session.execute(text(query))
            for row in result.fetchall():
                relation = PostgresRelation(schema_=row.schemaname, table=row.tablename)
                data.append(ListPublicationsItem(publication_name=row.pubname, relation=relation))

        return data

    def list_missing_publications(self) -> list[ListPublicationsItem]:
        """
        List expected publications missing from the source database.

        Compares local config (`list_expected_publications()`) against the
        source database (`list_actual_publications()`), ignoring expected
        items without a publication name because PeerDB manages those.

        Returns:
            list[ListPublicationsItem]: Expected items absent from the source.
        """
        actual = self.list_actual_publications()
        expected = self.list_expected_publications()
        # Exclude items that have no publication name because PeerDB will manage those publications
        expected = pydash.filter_(expected, lambda x: bool(x.publication_name))
        missing = pydash.difference(expected, actual)

        return missing

    def list_unused_publications(self) -> list[ListPublicationsItem]:
        """
        List source publications not present in the local config.

        Compares the source database (`list_actual_publications()`) against
        local config (`list_expected_publications()`).

        Returns:
            list[ListPublicationsItem]: Actual items absent from config.
        """
        actual = self.list_actual_publications()
        expected = self.list_expected_publications()
        unused = pydash.difference(actual, expected)

        return unused

    def list_replication_slots(self) -> list[ListReplicationSlotsItem]:
        """
        List replication slots in the source database.

        Runs a version-branched query over `pg_replication_slots`,
        `pg_control_checkpoint()`, `pg_stat_activity`, `pg_stat_replication`,
        and (on Postgres 16+) `pg_stat_replication_slots`, computing lag in MB.

        Modeled on the PeerDB slot query.

        See:
            https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/connectors/postgres/client.go#L295
            https://www.postgresql.org/docs/17/view-pg-replication-slots.html

        Returns:
            list[ListReplicationSlotsItem]: Replication slots for the source
                database.
        """
        # Source: https://github.com/PeerDB-io/peerdb/blob/v0.37.10/flow/connectors/postgres/client.go#L295
        POSTGRES_13 = 130000
        POSTGRES_16 = 160000

        source_adapter = self.get_peer_adapter(PEERDB_SOURCE_PEER)
        database = source_adapter.settings.database

        with source_adapter.create_session() as session:
            pg_version_str = session.execute(text("SHOW server_version_num")).scalar()
            pg_version = int(pg_version_str)

            wal_status_select = "'unknown' AS wal_status"
            safe_wal_size_select = "NULL::bigint AS safe_wal_size"
            if pg_version >= POSTGRES_13:
                wal_status_select = "prs.wal_status"
                safe_wal_size_select = "prs.safe_wal_size"

            ldw_mb_select = "NULL::bigint AS logical_decoding_work_mem_mb"
            if pg_version >= POSTGRES_13:
                ldw_mb_select = """(
                    SELECT (pg_size_bytes(setting || COALESCE(unit,'')) / 1024 / 1024)::bigint
                    FROM pg_settings WHERE name='logical_decoding_work_mem'
                ) AS logical_decoding_work_mem_mb"""

            stats_select = """
                NULL::bigint AS stats_reset,
                NULL::bigint AS spill_txns,
                NULL::bigint AS spill_count,
                NULL::bigint AS spill_bytes
            """
            stats_join = ""
            if pg_version >= POSTGRES_16:
                stats_select = """
                    EXTRACT(EPOCH FROM psrs.stats_reset)::bigint AS stats_reset,
                    psrs.spill_txns,
                    psrs.spill_count,
                    psrs.spill_bytes
                """
                stats_join = (
                    "LEFT JOIN pg_stat_replication_slots AS psrs ON psrs.slot_name = prs.slot_name"
                )

            query = f"""
                WITH current_wal AS (
                    SELECT CASE
                        WHEN pg_is_in_recovery()
                        THEN pg_last_wal_receive_lsn()
                        ELSE pg_current_wal_lsn()
                    END AS current_lsn
                )
                SELECT
                    prs.slot_name,
                    pcc.redo_lsn::text,
                    prs.restart_lsn::text,
                    cw.current_lsn::text,
                    {wal_status_select},
                    {safe_wal_size_select},
                    prs.confirmed_flush_lsn::text,
                    psr.sent_lsn::text,
                    prs.active,
                    prs.inactive_since,
                    round((cw.current_lsn - prs.restart_lsn) / 1024 / 1024)::bigint AS lag_mb,
                    round((prs.confirmed_flush_lsn - prs.restart_lsn) / 1024 / 1024)::bigint AS restart_to_confirmed_mb,
                    round((cw.current_lsn - prs.confirmed_flush_lsn) / 1024 / 1024)::bigint AS confirmed_to_current_mb,
                    psa.wait_event_type,
                    psa.wait_event,
                    psa.state AS backend_state,
                    {ldw_mb_select},
                    {stats_select},
                    prs.failover,
                    prs.synced
                FROM pg_replication_slots AS prs
                CROSS JOIN current_wal AS cw
                CROSS JOIN pg_control_checkpoint() AS pcc
                LEFT JOIN pg_stat_activity AS psa ON psa.pid = prs.active_pid
                LEFT JOIN pg_stat_replication AS psr ON psr.pid = prs.active_pid
                {stats_join}
                WHERE prs.database = :database
            """
            result = session.execute(text(query), params={"database": database})
            data = [ListReplicationSlotsItem(**row._asdict()) for row in result.fetchall()]

        return data


def find_config_file() -> Path:
    """
    Locate the PeerDB YAML config file.

    Uses `PEERDB_CONFIG_FILE` when set, otherwise searches upward from the
    current working directory for `peerdb.yaml`.

    Returns:
        Path: Resolved config file path.

    Raises:
        FileNotFoundError: If `PEERDB_CONFIG_FILE` points to a missing file.
        ConfigFileNotFoundException: If `peerdb.yaml` is not found upward.
    """
    config_file = os.environ.get("PEERDB_CONFIG_FILE")

    if config_file:
        config_path = Path(config_file)

        if not config_path.exists():
            raise FileNotFoundError(f"PEERDB_CONFIG_FILE '{config_file}' not found")

        return config_path

    filename = "peerdb.yaml"
    cwd = os.getcwd()
    config_file = find_up(cwd, filename)

    if not config_file:
        raise ConfigFileNotFoundException(f"{filename} not found in {cwd} or higher")

    return config_file
