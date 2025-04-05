from .constants import PEERDB_SOURCE_PEER
from .database.adapters.clickhouse import ClickHouseAdapter
from .database.adapters.postgres import PostgresAdapter
from .exceptions import MirrorNotFoundException
from .types import (
    ADAPTER_TYPE_TO_PEERDB_TYPE_MAP,
    AdapterType,
    ClickHouseSettings,
    PeerDBMirror,
    PeerDBPeer,
    PeerDBSetting,
    PostgresSettings,
    PostgresTableIdentifier,
)
from .utils.template import render_template
from pathlib import Path
from typing import Dict, List

import httpx
import pydash
import yaml


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

    def list_settings(self) -> List[PeerDBSetting]:
        url = f"{self.config['api_url']}/v1/dynamic_settings"
        response = httpx.get(url, headers=self._headers)
        settings = response.json().get("settings", [])
        settings = [PeerDBSetting(**setting) for setting in settings]

        return settings

    def update_settings(self, settings: Dict[str, str]) -> None:
        url = f"{self.config['api_url']}/v1/dynamic_settings"

        for key, value in settings.items():
            data = {"name": key, "value": value}
            response = httpx.post(url, json=data, headers=self._headers)

            if response.status_code != 200:
                raise Exception(
                    f"Failed to set {key}={value} (error {response.status_code}: {response.text})"
                )

    def list_peers(self) -> List[PeerDBPeer]:
        url = f"{self.config['api_url']}/v1/peers/list"
        response = httpx.get(url, headers=self._headers)
        peers = response.json().get("items", [])
        peers = [PeerDBPeer(**peer) for peer in peers]

        return peers

    def has_peer(self, peer: dict) -> bool:
        peers = self.list_peers()
        matched = pydash.find(peers, lambda x: x.name == peer["name"])

        return bool(matched)

    def create_peer(self, peer: dict) -> None:
        if not self.has_peer(peer):
            url = f"{self.config['api_url']}/v1/peers/create"
            data = {"peer": peer}
            response = httpx.post(url, json=data, headers=self._headers)
            status = response.json().get("status")

            if not (response.status_code == 200 and status == "CREATED"):
                raise Exception(
                    f"Failed to create peer '{peer['name']}' (error {response.status_code}: {response.text})"
                )

    def drop_peer(self, peer: dict) -> None:
        if self.has_peer(peer):
            url = f"{self.config['api_url']}/v1/peers/drop"
            data = {"peerName": peer["name"]}
            response = httpx.post(url, json=data, headers=self._headers, timeout=None)

            if not (response.status_code == 200):
                raise Exception(
                    f"Failed to drop peer '{peer['name']}' (error {response.status_code}: {response.text})"
                )

    def list_mirrors(self) -> List[PeerDBMirror]:
        url = f"{self.config['api_url']}/v1/mirrors/list"
        response = httpx.get(url, headers=self._headers)
        mirrors = response.json().get("mirrors", [])
        mirrors = [PeerDBMirror(**mirror) for mirror in mirrors]

        return mirrors

    def has_mirror(self, mirror: dict) -> bool:
        try:
            return self.get_mirror_status(mirror) != "STATUS_UNKNOWN"
        except MirrorNotFoundException:
            return False

    def get_mirror_status(self, mirror: dict) -> str | None:
        url = f"{self.config['api_url']}/v1/mirrors/status"
        data = {"flowJobName": mirror["flow_job_name"]}
        response = httpx.post(url, json=data, headers=self._headers)
        current_flow_state = response.json().get("currentFlowState")
        message = response.json().get("message", "")

        if response.status_code == 200:
            return current_flow_state
        elif (
            response.status_code == 500
            and "unable to get the workflow id of mirror" in message.lower()
        ):
            raise MirrorNotFoundException()
        else:
            raise Exception(
                f"Failed to get status of mirror '{mirror['flow_job_name']}' (error {response.status_code}: {response.text})"
            )

    def create_mirror(self, mirror: dict) -> None:
        if not self.has_mirror(mirror):
            url = f"{self.config['api_url']}/v1/flows/cdc/create"
            data = {"connection_configs": mirror}
            response = httpx.post(url, json=data, headers=self._headers)
            workflow_id = response.json().get("workflowId")

            if not (response.status_code == 200 and workflow_id):
                raise Exception(
                    f"Failed to create mirror '{mirror['flow_job_name']}' (error {response.status_code}: {response.text})"
                )

    def drop_mirror(self, mirror: dict) -> None:
        if self.has_mirror(mirror):
            url = f"{self.config['api_url']}/v1/mirrors/state_change"
            data = {
                "flowJobName": mirror["flow_job_name"],
                "requestedFlowState": "STATUS_TERMINATED",
            }
            response = httpx.post(url, json=data, headers=self._headers, timeout=None)

            if not (response.status_code == 200):
                raise Exception(
                    f"Failed to drop mirror '{mirror['flow_job_name']}' (error {response.status_code}: {response.text})"
                )


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
