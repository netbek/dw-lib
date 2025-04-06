from .constants import PEERDB_SOURCE_PEER
from .database.adapters.clickhouse import ClickHouseAdapter
from .database.adapters.postgres import PostgresAdapter
from .exceptions import MirrorNotFoundException
from .types import (
    ADAPTER_TYPE_TO_PEERDB_TYPE_MAP,
    AdapterType,
    ClickHouseSettings,
    ClickHouseTableIdentifier,
    PostgresSettings,
    PostgresTableIdentifier,
)
from .utils.template import render_template
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, List, Literal, Optional, Union

import httpx
import pydash
import yaml


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L48
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
    value: Optional[str] = None


class GetDynamicSettingsResponse(BaseModel):
    settings: List[DynamicSetting]


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/peers.proto#L111
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


class ClickHousePeer(BaseModel):
    type: Literal["CLICKHOUSE"]
    name: str
    clickhouse_config: ClickHouseConfig = Field(alias="clickhouseConfig")


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/peers.proto#L73
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


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L197
class PeerInfoResponse(BaseModel):
    peer: Union[PostgresPeer, ClickHousePeer]
    version: str


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L202
class PeerTypeResponse(BaseModel):
    peer_type: str = Field(alias="peerType")


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L206
class PeerListItem(BaseModel):
    name: str
    type: str


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L211
class ListPeersResponse(BaseModel):
    destination_items: List[PeerListItem] = Field(alias="destinationItems")
    items: List[PeerListItem]
    source_items: List[PeerListItem] = Field(alias="sourceItems")


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L106
class CreatePeerResponse(BaseModel):
    message: str
    status: Literal["CREATED"]


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L280
class MirrorStatusResponse(BaseModel):
    created_at: datetime = Field(alias="createdAt")
    current_flow_state: Literal["STATUS_SETUP", "STATUS_UNKNOWN"] = Field(alias="currentFlowState")
    flow_job_name: str = Field(alias="flowJobName")


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L345
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


# https://github.com/PeerDB-io/peerdb/blob/0890e1ea0151c45533cced93bdcb37d25dde66a5/protos/route.proto#L357
class ListMirrorsResponse(BaseModel):
    mirrors: List[ListMirrorsItem]


class PeerDB:
    def __init__(self, config_path: Path | str) -> None:
        self._config_path = config_path
        self._config = self._load_config()
        self._headers = {"Content-Type": "application/json"}

    @property
    def config(self) -> dict:
        return self._config

    def _load_config_data(self) -> dict:
        data = render_template(self._config_path)
        data = yaml.safe_load(data)
        return data

    def _load_config(self) -> dict:
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

        if "users" not in config:
            config["users"] = {}

        if "publications" in config:
            for key, value in config["publications"].items():
                config["publications"][key] = {
                    "name": key,
                    "table_identifiers": value,
                }
        else:
            config["publications"] = {}

        if "peers" in config:
            config["peers"] = process_node(config["peers"])

            for key, value in config["peers"].items():
                if value["type"] == AdapterType.CLICKHOUSE:
                    peerdb_config = {
                        "type": ADAPTER_TYPE_TO_PEERDB_TYPE_MAP[value["type"]],
                        "clickhouse_config": {
                            "host": value["settings"]["host"],
                            "port": value["settings"]["tcp_port"],
                            "user": value["settings"]["username"],
                            "password": value["settings"]["password"],
                            "database": value["settings"]["database"],
                            "disable_tls": not value["settings"]["secure"],
                        },
                    }
                elif value["type"] == AdapterType.POSTGRES:
                    peerdb_config = {
                        "type": ADAPTER_TYPE_TO_PEERDB_TYPE_MAP[value["type"]],
                        "postgres_config": {
                            "host": value["settings"]["host"],
                            "port": value["settings"]["port"],
                            "user": value["settings"]["username"],
                            "password": value["settings"]["password"],
                            "database": value["settings"]["database"],
                        },
                    }
                else:
                    raise Exception(f"Adapter type '{value['type']}' is not supported")

                config["peers"][key] = {
                    "name": key,
                    "adapter": value,
                    "peerdb": peerdb_config,
                }
        else:
            config["peers"] = {}

        if "mirrors" in config:
            config["mirrors"] = process_node(config["mirrors"])

            for key, value in config["mirrors"].items():
                config["mirrors"][key]["flow_job_name"] = key

            if config["mirrors"]:
                source_peer = config["peers"].get(PEERDB_SOURCE_PEER)

                if not source_peer:
                    raise Exception(f"Peer '{PEERDB_SOURCE_PEER}' not found in PeerDB config")

                source_adapter = PostgresAdapter(
                    PostgresSettings(**source_peer["adapter"]["settings"])
                )
                source_tables = source_adapter.list_tables()

                # Validate the table mappings
                for mirror in config["mirrors"].values():
                    for table_mapping in mirror["table_mappings"]:
                        # Find the source table in the source database
                        source_table_identifier = PostgresTableIdentifier.from_string(
                            table_mapping["source_table_identifier"]
                        )
                        source_table = pydash.find(
                            source_tables,
                            lambda table: (
                                table.schema == source_table_identifier.schema_
                                and table.name == source_table_identifier.table
                            ),
                        )

                        if source_table is None:
                            raise Exception(
                                f"Source table '{table_mapping['source_table_identifier']}' not found in database of peer '{PEERDB_SOURCE_PEER}'"
                            )
        else:
            config["mirrors"] = {}

        publication_schemas = []

        for value in config["publications"].values():
            for identifier in value["table_identifiers"]:
                source_table_identifier = PostgresTableIdentifier.from_string(identifier)
                publication_schemas.append(source_table_identifier.schema_)

        for value in config["mirrors"].values():
            for table_mapping in value["table_mappings"]:
                source_table_identifier = PostgresTableIdentifier.from_string(
                    table_mapping["source_table_identifier"]
                )
                publication_schemas.append(source_table_identifier.schema_)

        config["publication_schemas"] = sorted(pydash.uniq(publication_schemas))

        return config

    def get_settings(self) -> GetDynamicSettingsResponse:
        url = f"{self.config['api_url']}/v1/dynamic_settings"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to get dynamic settings (error {response.status_code}: {response.text})"
            )

        return GetDynamicSettingsResponse(**response.json())

    def update_settings(self, settings: Dict[str, str]) -> None:
        url = f"{self.config['api_url']}/v1/dynamic_settings"

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
        url = f"{self.config['api_url']}/v1/peers/info/{peer_name}"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to peer info of '{peer_name}' (error {response.status_code}: {response.text})"
            )

        return PeerInfoResponse(**response.json())

    def get_peer_type(self, peer_name: str) -> PeerTypeResponse:
        url = f"{self.config['api_url']}/v1/peers/type/{peer_name}"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to peer type of '{peer_name}' (error {response.status_code}: {response.text})"
            )

        return PeerTypeResponse(**response.json())

    def create_peer(self, peer: dict) -> CreatePeerResponse:
        if not self.has_peer(peer):
            url = f"{self.config['api_url']}/v1/peers/create"
            data = {"peer": peer}
            response = httpx.post(url, json=data, headers=self._headers)

            if response.status_code != 200:
                raise Exception(
                    f"Failed to create peer '{peer['name']}' (error {response.status_code}: {response.text})"
                )

            deserialized = CreatePeerResponse(**response.json())

            if deserialized.status != "CREATED":
                raise Exception(
                    f"Failed to create peer '{peer['name']}' (status {deserialized.status})"
                )

            return deserialized

    def drop_peer(self, peer_name: str, drop_destination_tables: Optional[bool] = False) -> None:
        if self.has_peer(peer_name):
            url = f"{self.config['api_url']}/v1/peers/drop"
            data = {"peerName": peer_name}
            response = httpx.post(url, json=data, headers=self._headers, timeout=None)

            if response.status_code != 200:
                raise Exception(
                    f"Failed to drop peer '{peer_name}' (error {response.status_code}: {response.text})"
                )

            # TODO Drop mirrors

    def list_peers(self) -> ListPeersResponse:
        url = f"{self.config['api_url']}/v1/peers/list"
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
        url = f"{self.config['api_url']}/v1/mirrors/status"
        data = {"flowJobName": flow_job_name}
        response = httpx.post(url, json=data, headers=self._headers)
        message = response.json().get("message", "")

        if response.status_code == 200:
            return MirrorStatusResponse(**response.json())
        elif (
            response.status_code == 500
            and "unable to get the workflow id of mirror" in message.lower()
        ):
            raise MirrorNotFoundException()
        else:
            raise Exception(
                f"Failed to get status of mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
            )

    def create_mirror(self, mirror: dict) -> None:
        if not self.has_mirror(mirror["flow_job_name"]):
            url = f"{self.config['api_url']}/v1/flows/cdc/create"
            data = {"connection_configs": mirror}
            response = httpx.post(url, json=data, headers=self._headers)
            workflow_id = response.json().get("workflowId")

            if not (response.status_code == 200 and workflow_id):
                raise Exception(
                    f"Failed to create mirror '{mirror['flow_job_name']}' (error {response.status_code}: {response.text})"
                )

    def drop_mirror(
        self, flow_job_name: str, drop_destination_tables: Optional[bool] = False
    ) -> None:
        if self.has_mirror(flow_job_name):
            url = f"{self.config['api_url']}/v1/mirrors/state_change"
            data = {"flowJobName": flow_job_name, "requestedFlowState": "STATUS_TERMINATED"}
            response = httpx.post(url, json=data, headers=self._headers, timeout=None)

            if response.status_code != 200:
                raise Exception(
                    f"Failed to drop mirror '{flow_job_name}' (error {response.status_code}: {response.text})"
                )

        if drop_destination_tables:
            mirror = pydash.find(
                self.config["mirrors"].values(), lambda x: x["flow_job_name"] == flow_job_name
            )
            destination_name = mirror["destination_name"]
            peer_config = self.config["peers"][destination_name]
            clickhouse_settings = ClickHouseSettings(**peer_config["adapter"]["settings"])
            clickhouse_adapter = ClickHouseAdapter(clickhouse_settings)

            for table_mapping in mirror["table_mappings"]:
                table_identifier = ClickHouseTableIdentifier.from_string(
                    table_mapping["destination_table_identifier"]
                )
                clickhouse_adapter.drop_table(**table_identifier.model_dump())

    def list_mirrors(self) -> ListMirrorsResponse:
        url = f"{self.config['api_url']}/v1/mirrors/list"
        response = httpx.get(url, headers=self._headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to list mirrors (error {response.status_code}: {response.text})"
            )

        return ListMirrorsResponse(**response.json())


class SourcePeer(PostgresAdapter):
    def create_user(self, username: str, password: str) -> None:
        return super().create_user(username, password, options={"login": True, "replication": True})


class DestinationPeer(ClickHouseAdapter):
    def __init__(self, db_settings: ClickHouseSettings, database: str) -> None:
        self._database = database
        super().__init__(db_settings)

    @property
    def database(self) -> str:
        return self._database
