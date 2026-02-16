from .database.adapters.clickhouse import ClickHouseAdapter
from .database.adapters.postgres import PostgresAdapter
from .exceptions import (
    EmptyConfigException,
    MirrorExistsException,
    MirrorNotFoundException,
    PeerExistsException,
    PeerNotFoundException,
    TableNotFoundException,
)
from .types import (
    ClickHouseRelation,
    ClickHouseSettings,
    PostgresRelation,
    PostgresSettings,
)
from .utils.filesystem import find_up
from .utils.template import render_template
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from sqlglot.dialects.dialect import Dialects
from sqlmodel import text
from typing import Literal

import httpx
import os
import pydash
import rich
import time
import yaml

PEERDB_SOURCE_PEER = "source"
PEERDB_DESTINATION_PEER = "destination"

# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/peers.proto#L261
DIALECT_TO_PEERDB_TYPE_MAP = {
    Dialects.POSTGRES: 3,
    Dialects.CLICKHOUSE: 8,
}


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/flow.proto#L460
class FlowStatus:
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


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L39
class DynamicSetting(BaseModel):
    name: str
    default_value: str = Field(alias="defaultValue")
    description: str
    value_type: Literal["INT", "UINT", "STRING", "BOOL"] = Field(alias="valueType")
    apply_mode: Literal[
        "APPLY_MODE_IMMEDIATE", "APPLY_MODE_AFTER_RESUME", "APPLY_MODE_NEW_MIRROR"
    ] = Field(alias="applyMode")
    target_for_setting: Literal["ALL", "QUEUES", "CLICKHOUSE", "SNOWFLAKE", "BIGQUERY"] = Field(
        alias="targetForSetting"
    )
    value: str | None = None


class GetDynamicSettingsResponse(BaseModel):
    settings: list[DynamicSetting]


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/peers.proto#L170
class ClickHouseConfig(BaseModel):
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
    type: Literal["CLICKHOUSE"]
    name: str
    clickhouse_config: ClickHouseConfig = Field(alias="clickhouseConfig")


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/peers.proto#L117
class PostgresConfig(BaseModel):
    host: str
    port: int
    database: str
    user: str
    password: str


class PostgresPeer(BaseModel):
    type: Literal["POSTGRES"]
    name: str
    postgres_config: PostgresConfig = Field(alias="postgresConfig")


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L216
class PeerInfoResponse(BaseModel):
    peer: ClickHousePeer | PostgresPeer
    version: str


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L221
class PeerTypeResponse(BaseModel):
    peer_type: str = Field(alias="peerType")


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L225
class PeerListItem(BaseModel):
    name: str
    type: str


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L230
class ListPeersResponse(BaseModel):
    destination_items: list[PeerListItem] = Field(alias="destinationItems")
    items: list[PeerListItem]
    source_items: list[PeerListItem] = Field(alias="sourceItems")


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L98
class RawCreatePeerResponse(BaseModel):
    message: str
    status: Literal["VALIDATION_UNKNOWN", "CREATED", "FAILED"]


class CreatePeerResponse(BaseModel):
    message: str
    response: RawCreatePeerResponse | None = None


class DropPeerResponse(BaseModel):
    message: str


class RawCreateMirrorResponse(BaseModel):
    workflow_id: str = Field(alias="workflowId")


class CreateMirrorResponse(BaseModel):
    message: str
    response: RawCreateMirrorResponse | None = None


class DropMirrorResponse(BaseModel):
    message: str


class ResyncMirrorResponse(BaseModel):
    message: str


class PauseMirrorResponse(BaseModel):
    message: str


class ResumeMirrorResponse(BaseModel):
    message: str


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L313
class MirrorStatusResponse(BaseModel):
    created_at: datetime = Field(alias="createdAt")
    # https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/flow.proto#L460
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


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L398
class ListMirrorsItem(BaseModel):
    id: str
    workflow_id: str = Field(alias="workflowId")
    name: str
    source_name: str = Field(alias="sourceName")
    source_type: str = Field(alias="sourceType")
    destination_name: str = Field(alias="destinationName")
    destination_type: str = Field(alias="destinationType")
    created_at: datetime = Field(alias="createdAt")
    is_cdc: bool = Field(alias="isCdc")


# https://github.com/PeerDB-io/peerdb/blob/v0.36.6/protos/route.proto#L410
class ListMirrorsResponse(BaseModel):
    mirrors: list[ListMirrorsItem]


class ListPublicationsItem(BaseModel):
    publication_name: str
    relation: PostgresRelation


class ListReplicationSlotsItem(BaseModel):
    name: str
    active: bool
    inactive_since: datetime | None = None
    restart_lsn: str | None = None
    restart_lag: str | None = None
    confirmed_flush_lsn: str | None = None
    confirmed_flush_lag: str | None = None
    failover: bool
    synced: bool


class ConfigSetting(BaseModel):
    name: str
    value: str


class ConfigPeerAdapterClickHouse(BaseModel):
    type: str
    settings: ClickHouseSettings


class ConfigPeerPeerDBClickHouseConfig(BaseModel):
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
    def validate_tls_fields(self) -> "ConfigPeerPeerDBClickHouseConfig":
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
    type: Literal[8]
    clickhouse_config: ConfigPeerPeerDBClickHouseConfig


class ConfigPeerClickHouse(BaseModel):
    name: str
    adapter: ConfigPeerAdapterClickHouse
    peerdb: ConfigPeerPeerDBClickHouse


class ConfigPeerAdapterPostgres(BaseModel):
    type: str
    settings: PostgresSettings


class SSHConfig(BaseModel):
    host: str
    port: int
    user: str
    private_key: str


class ConfigPeerPeerDBPostgresConfig(BaseModel):
    host: str
    port: int
    database: str
    user: str
    password: str
    ssh_config: SSHConfig | None = None


class ConfigPeerPeerDBPostgres(BaseModel):
    type: Literal[3]
    postgres_config: ConfigPeerPeerDBPostgresConfig


class ConfigPeerPostgres(BaseModel):
    name: str
    adapter: ConfigPeerAdapterPostgres
    peerdb: ConfigPeerPeerDBPostgres


class ConfigMirrorTableMapping(BaseModel):
    source_table_identifier: str
    destination_table_identifier: str


class ConfigMirror(BaseModel):
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


# class ConfigPublication(BaseModel):
#     name: str
#     table_identifiers: list[str]


class Config(BaseModel):
    api_url: str
    settings: list[ConfigSetting] | None = None
    peers: list[ConfigPeerClickHouse | ConfigPeerPostgres]
    mirrors: list[ConfigMirror]
    # publications: list[ConfigPublication]


class PeerDB:
    def __init__(self, config_file: Path | str) -> None:
        self._config_file = config_file
        self._config = self._load_config()
        self._headers = {"Content-Type": "application/json"}
        self._console = rich.console.Console()

    @property
    def config(self) -> Config:
        return self._config

    def _load_config_data(self) -> dict:
        data = render_template(self._config_file)
        data = yaml.safe_load(data)
        return data

    def _load_config(self) -> Config:
        def process_node(node: dict) -> dict:
            default_keys = [key for key in node.keys() if key.startswith("+")]
            defaults = {key.lstrip("+").strip(): node[key] for key in default_keys}

            if defaults:
                for key in node.keys():
                    if not key.startswith("+"):
                        node[key] = pydash.defaults(node[key], defaults)

                node = pydash.omit(node, *default_keys)

            return node

        config = self._load_config_data()

        if not config:
            raise EmptyConfigException()

        settings = []
        peers = []
        mirrors = []
        # publications = []

        if "settings" in config:
            settings = [{"name": key, "value": value} for key, value in config["settings"].items()]

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
                            "port": value["settings"]["tcp_port"],
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
                    raise Exception(f"Adapter type '{value['type']}' is not supported")

                peers.append(
                    {
                        "name": key,
                        "adapter": adapter_config,
                        "peerdb": peerdb_config,
                    }
                )

        if "mirrors" in config:
            config["mirrors"] = process_node(config["mirrors"])

            for key in config["mirrors"].keys():
                config["mirrors"][key]["flow_job_name"] = key

            mirrors = list(config["mirrors"].values())

        # if "publications" in config:
        #     for key, value in config["publications"].items():
        #         publications.append({"name": key, "table_identifiers": value})

        return Config(
            api_url=config.get("api_url"),
            settings=settings,
            peers=peers,
            mirrors=mirrors,
            # publications=publications,
        )

    def can_connect(self) -> bool:
        url = f"{self.config.api_url}/v1/version"
        response = httpx.get(url, headers=self._headers)

        return response.status_code == 200

    def debug(self, echo: bool = False) -> dict[str, dict[str, str]] | None:
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

        def render_table(data, title: str | None = None) -> rich.table.Table:
            table = rich.table.Table(title=title, show_header=True, min_width=80)

            headers = data[0].keys()
            for header in headers:
                table.add_column(header)

            for item in data:
                table.add_row(*[str(value) for value in item.values()])

            return table

        try:
            self.get_settings()
            api_can_connect = True
        except Exception:
            api_can_connect = False

        source_adapter = self.get_peer_adapter(PEERDB_SOURCE_PEER)
        destination_adapter = self.get_peer_adapter(PEERDB_DESTINATION_PEER)
        source_can_connect = source_adapter.can_connect()
        destination_can_connect = destination_adapter.can_connect()

        # Check settings of source peer
        # https://docs.peerdb.io/usecases/Real-time%20CDC/postgres-to-postgres#prerequisites
        if source_can_connect:
            with source_adapter.create_client() as (conn, cur):
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
            max_replication_slots_is_valid = None
            max_wal_senders_is_valid = None
            wal_level_is_valid = None

        result = {
            "API": {
                "URL": self.config.api_url,
                "Connection test": create_message(api_can_connect),
            },
            "Source peer": {
                "URL": str(source_adapter.url),
                "Connection test": create_message(source_can_connect),
                "max_replication_slots >= 4": create_message(max_replication_slots_is_valid),
                "max_wal_senders >= 1": create_message(max_wal_senders_is_valid),
                "wal_level = logical": create_message(wal_level_is_valid),
            },
            "Destination peer": {
                "URL": str(destination_adapter.url),
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
            data = [
                {
                    "publication": publication.publication_name,
                    "schema": publication.relation.schema_,
                    "table": publication.relation.table,
                }
                for publication in self.list_missing_publications()
            ]
            if data:
                self._console.print(render_table(data, title="Missing publications"))
            else:
                self._console.print("Missing publications: [green]OK (None)[/green]")

            # Unused publications
            self._console.print()
            data = [
                {
                    "publication": publication.publication_name,
                    "schema": publication.relation.schema_,
                    "table": publication.relation.table,
                }
                for publication in self.list_unused_publications()
            ]
            if data:
                self._console.print(render_table(data, title="Unused publications"))
            else:
                self._console.print("Unused publications: [green]OK (None)[/green]")

            # # Peers
            # self._console.print()
            # data = [peer.model_dump() for peer in self.list_peers().items]
            # if data:
            #     self._console.print(render_table(data, title="Peers"))
            # else:
            #     self._console.print("Peers: None")

            # Mirrors
            self._console.print()
            data = []
            for mirror in self.list_mirrors().mirrors:
                status_response = self.get_mirror_status(mirror.name)
                data.append(
                    pydash.pick(
                        {**mirror.model_dump(), "status": status_response.current_flow_state},
                        "name",
                        "created_at",
                        "status",
                    )
                )
            data = pydash.order_by(data, ["name"])
            if data:
                self._console.print(render_table(data, title="Mirrors"))
            else:
                self._console.print("Mirrors: None")

            # Replication slots
            self._console.print()
            data = [slot.model_dump() for slot in self.list_replication_slots()]
            if data:
                self._console.print(render_table(data, title="Replication slots"))
            else:
                self._console.print("Replication slots: None")

        return result

    def get_peer_adapter(self, peer_name: str) -> ClickHouseAdapter | PostgresAdapter:
        peer = pydash.find(self.config.peers, lambda x: x.name == peer_name)

        if not peer:
            raise PeerNotFoundException(f"Peer '{peer_name}' not found")

        if peer.adapter.type == Dialects.CLICKHOUSE:
            return ClickHouseAdapter(peer.adapter.settings)
        elif peer.adapter.type == Dialects.POSTGRES:
            return PostgresAdapter(peer.adapter.settings)
        else:
            raise Exception(f"Peer type '{peer.adapter.type}' has no adapter")

    def get_settings(self) -> GetDynamicSettingsResponse:
        url = f"{self.config.api_url}/v1/dynamic_settings"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to get dynamic settings (error {response.status_code}: {response.text})"
            )

        return GetDynamicSettingsResponse(**response.json())

    def update_settings(self, settings: dict[str, str]) -> None:
        self._console.print("Updating settings")

        url = f"{self.config.api_url}/v1/dynamic_settings"

        for key, value in settings.items():
            data = {"name": key, "value": value}
            response = httpx.post(url, json=data, headers=self._headers)

            if response.status_code != 200:
                raise Exception(
                    f"Failed to set {key}={value} (error {response.status_code}: {response.text})"
                )

    def has_peer(self, peer_name: str) -> bool:
        response = self.list_peers()
        matched = pydash.find(response.items, lambda x: x.name == peer_name)

        return bool(matched)

    def get_peer_info(self, peer_name: str) -> PeerInfoResponse:
        url = f"{self.config.api_url}/v1/peers/info/{peer_name}"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to peer info of '{peer_name}' (error {response.status_code}: {response.text})"
            )

        return PeerInfoResponse(**response.json())

    def get_peer_type(self, peer_name: str) -> PeerTypeResponse:
        url = f"{self.config.api_url}/v1/peers/type/{peer_name}"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to peer type of '{peer_name}' (error {response.status_code}: {response.text})"
            )

        return PeerTypeResponse(**response.json())

    def create_peer(
        self, peer: dict, if_exists: Literal["fail", "keep", "replace"] = "fail"
    ) -> CreatePeerResponse:
        self._console.print(f"Creating peer '{peer['name']}'")

        has_peer = self.has_peer(peer["name"])

        if has_peer:
            if if_exists == "keep":
                return CreatePeerResponse(message=f"Kept peer '{peer['name']}'")
            elif if_exists == "replace":
                self.drop_peer(peer["name"], drop_mirrors=True, drop_destination_tables=True)
            else:
                raise PeerExistsException(f"Peer '{peer['name']}' exists")

        url = f"{self.config.api_url}/v1/peers/create"
        data = {"peer": peer}
        response = httpx.post(url, json=data, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to create peer '{peer['name']}' (error {response.status_code}: {response.text})"
            )

        deserialized = RawCreatePeerResponse(**response.json())

        if deserialized.status != "CREATED":
            raise Exception(
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
    ) -> DropPeerResponse:
        self._console.print(f"Dropping peer '{peer_name}'")

        if drop_mirrors:
            self.drop_mirrors_of_peer(peer_name, drop_destination_tables=drop_destination_tables)

        if not self.has_peer(peer_name):
            if if_exists:
                return DropPeerResponse(
                    message=f"Peer '{peer_name}' not found, skipping because if_exists=True"
                )
            else:
                raise PeerNotFoundException(f"Peer '{peer_name}' not found")

        url = f"{self.config.api_url}/v1/peers/drop"
        data = {"peerName": peer_name}
        response = httpx.post(url, json=data, headers=self._headers, timeout=None)

        if response.status_code != 200:
            raise Exception(
                f"Failed to drop peer '{peer_name}' (error {response.status_code}: {response.text})"
            )

        return DropPeerResponse(message=f"Dropped peer '{peer_name}'")

    def drop_mirrors_of_peer(
        self, peer_name: str, drop_destination_tables: bool | None = False
    ) -> None:
        for mirror in self.list_mirrors().mirrors:
            if mirror.source_name == peer_name or mirror.destination_name == peer_name:
                self.drop_mirror(mirror.name, drop_destination_tables=drop_destination_tables)

    def list_peers(self) -> ListPeersResponse:
        url = f"{self.config.api_url}/v1/peers/list"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(f"Failed to list peers (error {response.status_code}: {response.text})")

        return ListPeersResponse(**response.json())

    def has_mirror(self, flow_job_name: str) -> bool:
        try:
            return self.get_mirror_status(flow_job_name).current_flow_state != "STATUS_UNKNOWN"
        except MirrorNotFoundException:
            return False

    def get_mirror_status(self, flow_job_name: str) -> MirrorStatusResponse:
        url = f"{self.config.api_url}/v1/mirrors/status"
        data = {"flowJobName": flow_job_name}
        response = httpx.post(url, json=data, headers=self._headers)
        message = response.json().get("message", "")

        if response.status_code == 200:
            return MirrorStatusResponse(**response.json())
        # TODO Check what the canonical status code is. Older versions of PeerDB returned code 500
        # and the workflow message. PeerDB v0.34.5 returns code 404.
        elif response.status_code == 404 or (
            response.status_code == 500
            and "unable to get the workflow id of mirror" in message.lower()
        ):
            raise MirrorNotFoundException()
        else:
            raise Exception(
                f"Failed to get status of mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
            )

    def wait_for_mirror_status(
        self,
        flow_job_name: str,
        target_statuses: set[str],
        timeout: int = 15,
        polling_interval: int = 1,
    ) -> str:
        current_status = "UNKNOWN"

        for _ in range(timeout):
            current_status = self.get_mirror_status(flow_job_name).current_flow_state

            if current_status in target_statuses:
                return current_status

            time.sleep(polling_interval)
        else:
            raise Exception(
                f"Timeout: Mirror '{flow_job_name}' failed to reach status {target_statuses} after {timeout}s (current status: {current_status})"
            )

    def create_mirror(
        self, mirror: dict, if_exists: Literal["fail", "keep", "replace"] = "fail"
    ) -> CreateMirrorResponse:
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
            raise Exception(f"Peer '{mirror['source_name']}' not found in PeerDB config")

        if source_peer.adapter.type != Dialects.POSTGRES:
            raise Exception(f"Adapter type '{source_peer.adapter.type}' is not supported")

        source_adapter = PostgresAdapter(
            PostgresSettings(**source_peer.adapter.settings.model_dump())
        )
        source_tables = source_adapter.list_tables()

        for table_mapping in mirror["table_mappings"]:
            source_relation = PostgresRelation.from_string(table_mapping["source_table_identifier"])
            source_table = pydash.find(
                source_tables,
                lambda x: x.schema == source_relation.schema_ and x.name == source_relation.table,
            )

            if source_table is None:
                raise TableNotFoundException(
                    f"Source table '{table_mapping['source_table_identifier']}' not found in database of peer '{source_peer.name}'"
                )

        # Step 2: Drop the destination tables
        self.drop_destination_tables_of_mirror(mirror["flow_job_name"])

        # Step 3: Create the mirror
        url = f"{self.config.api_url}/v1/flows/cdc/create"
        data = {"connection_configs": mirror}
        response = httpx.post(url, json=data, headers=self._headers)
        workflow_id = response.json().get("workflowId")

        if not (response.status_code == 200 and workflow_id):
            raise Exception(
                f"Failed to create mirror '{mirror['flow_job_name']}' (error {response.status_code}: {response.text})"
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
        timeout: int = 15,
    ) -> DropMirrorResponse:
        self._console.print(f"Dropping mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            if if_exists:
                return DropMirrorResponse(
                    f"Mirror '{flow_job_name}' not found, skipping because if_exists=True"
                )
            else:
                raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        url = f"{self.config.api_url}/v1/mirrors/state_change"
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": FlowStatus.STATUS_TERMINATING,
            "dropMirrorStats": True,
            "skipDestinationDrop": False,
        }
        response = httpx.post(url, json=data, headers=self._headers, timeout=None)

        if response.status_code != 200:
            raise Exception(
                f"Failed to drop mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
            )

        for _ in range(timeout):
            if not self.has_mirror(flow_job_name):
                break
            time.sleep(1)
        else:
            raise Exception(f"Failed to drop mirror '{flow_job_name}' after {timeout}s")

        if drop_destination_tables:
            self.drop_destination_tables_of_mirror(flow_job_name)

        return DropMirrorResponse(message=f"Dropped mirror '{flow_job_name}'")

    def resync_mirror(
        self, flow_job_name: str, if_exists: bool | None = False, timeout: int = 15
    ) -> ResyncMirrorResponse:
        self._console.print(f"Resyncing mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            if if_exists:
                return ResyncMirrorResponse(
                    f"Mirror '{flow_job_name}' not found, skipping because if_exists=True"
                )
            else:
                raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        url = f"{self.config.api_url}/v1/mirrors/state_change"
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": FlowStatus.STATUS_RESYNC,
            "dropMirrorStats": True,
        }
        response = httpx.post(url, json=data, headers=self._headers, timeout=None)

        if response.status_code != 200:
            raise Exception(
                f"Failed to resync mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
            )

        self.wait_for_mirror_status(flow_job_name, {"STATUS_RESYNC"}, timeout=timeout)

        return ResyncMirrorResponse(
            message=f"Resync of mirror '{flow_job_name}' has been initiated"
        )

    def pause_mirror(self, flow_job_name: str, timeout: int = 15) -> PauseMirrorResponse:
        self._console.print(f"Pausing mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        current_flow_state = self.get_mirror_status(flow_job_name).current_flow_state
        if current_flow_state not in {"STATUS_RUNNING"}:
            return PauseMirrorResponse(
                message=f"Not pausing mirror '{flow_job_name}' because its status is '{current_flow_state}'"
            )

        url = f"{self.config.api_url}/v1/mirrors/state_change"
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": "STATUS_PAUSED",
        }
        response = httpx.post(url, json=data, headers=self._headers, timeout=None)

        if response.status_code != 200:
            raise Exception(
                f"Failed to pause mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
            )

        self.wait_for_mirror_status(flow_job_name, {"STATUS_PAUSED"}, timeout=timeout)

        return PauseMirrorResponse(message=f"Paused mirror '{flow_job_name}'")

    def resume_mirror(self, flow_job_name: str, timeout: int = 15) -> ResumeMirrorResponse:
        self._console.print(f"Resuming mirror '{flow_job_name}'")

        if not self.has_mirror(flow_job_name):
            raise MirrorNotFoundException(f"Mirror '{flow_job_name}' not found")

        current_flow_state = self.get_mirror_status(flow_job_name).current_flow_state
        if current_flow_state not in {"STATUS_PAUSED", "STATUS_PAUSING"}:
            return ResumeMirrorResponse(
                message=f"Not resuming mirror '{flow_job_name}' because its status is '{current_flow_state}'"
            )

        url = f"{self.config.api_url}/v1/mirrors/state_change"
        data = {
            "flowJobName": flow_job_name,
            "requestedFlowState": "STATUS_RUNNING",
        }
        response = httpx.post(url, json=data, headers=self._headers, timeout=None)

        if response.status_code != 200:
            raise Exception(
                f"Failed to resume mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
            )

        self.wait_for_mirror_status(flow_job_name, {"STATUS_RUNNING"}, timeout=timeout)

        return ResumeMirrorResponse(message=f"Resumed mirror '{flow_job_name}'")

    def drop_destination_tables_of_mirror(self, flow_job_name: str) -> None:
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
            raise Exception(f"Adapter type '{destination_peer.adapter.type}' is not supported")

        destination_adapter = adapter_class(
            settings_class(**destination_peer.adapter.settings.model_dump())
        )
        destination_relations = [
            relation_class.from_string(table_mapping.destination_table_identifier)
            for table_mapping in mirror.table_mappings
        ]

        for relation in destination_relations:
            destination_adapter.drop_table(**relation.model_dump(by_alias=True), if_exists=True)

    def list_mirrors(self) -> ListMirrorsResponse:
        url = f"{self.config.api_url}/v1/mirrors/list"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to list mirrors (error {response.status_code}: {response.text})"
            )

        return ListMirrorsResponse(mirrors=pydash.sort_by(response.json()["mirrors"], "name"))

    def list_expected_publications(self) -> list[ListPublicationsItem]:
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
        source_adapter = self.get_peer_adapter(PEERDB_SOURCE_PEER)
        data = []
        with source_adapter.create_session() as session:
            query = """
            SELECT pubname, schemaname, tablename
            FROM pg_publication_tables
            ORDER BY pubname, schemaname, tablename
            """
            result = session.exec(text(query))
            for row in result.fetchall():
                relation = PostgresRelation(schema_=row.schemaname, table=row.tablename)
                data.append(ListPublicationsItem(publication_name=row.pubname, relation=relation))

        return data

    def list_missing_publications(self) -> list[ListPublicationsItem]:
        """List the publications in the configuration that are not in the source database."""
        actual = self.list_actual_publications()
        expected = self.list_expected_publications()
        # Exclude items that have no publication name because PeerDB will manage those publications
        expected = pydash.filter_(expected, lambda x: bool(x.publication_name))
        missing = pydash.difference(expected, actual)

        return missing

    def list_unused_publications(self) -> list[ListPublicationsItem]:
        """List the publications in the source database that are not in the configuration."""
        actual = self.list_actual_publications()
        expected = self.list_expected_publications()
        unused = pydash.difference(actual, expected)

        return unused

    def list_replication_slots(self) -> list[ListReplicationSlotsItem]:
        """List the replication slots in the source database."""
        source_adapter = self.get_peer_adapter(PEERDB_SOURCE_PEER)
        database = source_adapter.settings.database
        data = []
        with source_adapter.create_session() as session:
            # TODO Check whether `database` is not null in a read replica deployment
            query = """
            SELECT
                slot_name AS name,
                active,
                inactive_since,
                restart_lsn,
                pg_size_pretty(pg_wal_lsn_diff(
                    CASE
                        WHEN pg_is_in_recovery() THEN pg_last_wal_receive_lsn()
                        ELSE pg_current_wal_lsn()
                    END,
                    restart_lsn
                )) AS restart_lag,
                confirmed_flush_lsn,
                pg_size_pretty(pg_wal_lsn_diff(
                    CASE
                        WHEN pg_is_in_recovery() THEN pg_last_wal_receive_lsn()
                        ELSE pg_current_wal_lsn()
                    END,
                    confirmed_flush_lsn
                )) AS confirmed_flush_lag,
                failover,
                synced
            FROM pg_replication_slots
            WHERE database = :database
            ORDER BY slot_name
            """
            result = session.exec(text(query), params={"database": database})
            for row in result.fetchall():
                data.append(ListReplicationSlotsItem(**row._asdict()))

        return data


def find_config_file() -> Path:
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
        raise Exception(f"{filename} not found in {cwd} or higher")

    return config_file
