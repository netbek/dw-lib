from .cloud.adapters.s3 import S3Adapter
from .database.adapters import PostgresAdapter
from .exceptions import ConnectionNotFoundException, StreamNotFoundException
from .types import PostgresSettings, PostgresTableIdentifier, S3Settings
from .utils.filesystem import find_up
from .utils.yaml_utils import safe_load_file
from chdb import session
from enum import StrEnum
from jinja2 import Template
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from urllib.parse import urlparse

import json
import os
import pydash
import re
import rich

RE_DATABASE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$")
RE_LOCAL_FILE = re.compile(r"^file://")
RE_CLOUD_FILE = re.compile(r"^s3://")


class ConnectionType(StrEnum):
    POSTGRES = "postgres"
    S3 = "s3"


class PostgresConnection(BaseModel):
    type: str = ConnectionType.POSTGRES
    settings: PostgresSettings


class S3Connection(BaseModel):
    type: str = ConnectionType.S3
    settings: S3Settings


Connection = PostgresConnection | S3Connection

Connections = dict[str, Connection]


class ClickHouseColumn(BaseModel):
    name: str
    type: str
    default_type: str
    default_expression: str
    comment: str
    codec_expression: str
    ttl_expression: str


class PostgresColumn(BaseModel):
    name: str
    data_type: str
    udt_name: str
    description: str | None = None


class BaseStream(BaseModel):
    destination: str
    partition_by: str | None = None
    columns: list[str] | None = None
    sql: str | None = None

    @model_validator(mode="after")
    def ensure_columns_or_sql(self):
        if self.columns and self.sql:
            raise ValueError("Either 'columns' or 'sql' must be provided, not both")
        return self


class DatabaseStream(BaseStream):
    """Database-based stream: schema.table"""

    source: PostgresTableIdentifier

    @model_validator(mode="before")
    @classmethod
    def parse_source(cls, values):
        source = values.get("source")
        if isinstance(source, str):
            values["source"] = PostgresTableIdentifier.from_string(source)

        return values

    def render_stream_select(self, source_connection: Connection) -> str:
        source = (
            f"postgresql('{source_connection.settings.host}:{source_connection.settings.port}', "
            f"'{source_connection.settings.database}', '{self.source.table}', "
            f"'{source_connection.settings.username}', '{source_connection.settings.password}', "
            f"'{self.source.schema_}')"
        )

        if self.sql:
            sql = Template(self.sql).render({"source": source})
        else:
            if self.columns:
                columns_str = ", ".join(self.columns)
            else:
                columns_str = "*"
            sql = Template("SELECT {{ columns }} FROM {{ source }}").render(
                {"source": source, "columns": columns_str}
            )

        return sql

    def list_stream_columns(self, source_connection: Connection) -> list[ClickHouseColumn]:
        sql = self.render_stream_select(source_connection)
        sql = Template("DESCRIBE (SELECT * FROM ({{ sql }}) LIMIT 0)").render({"sql": sql})

        with session.Session() as sess:
            result = sess.query(sql, "JSON")
        columns = json.loads(str(result))["data"]

        return [ClickHouseColumn(**column) for column in columns]


class LocalFileStream(BaseStream):
    """Local file stream: file://..."""

    source: str = Field(pattern=RE_LOCAL_FILE.pattern)


class CloudFileStream(BaseStream):
    """Cloud file stream: s3://..."""

    source: str = Field(pattern=RE_CLOUD_FILE.pattern)


Stream = DatabaseStream | LocalFileStream | CloudFileStream


class Config(BaseModel):
    connections: Connections
    streams: list[Stream]

    @model_validator(mode="before")
    @classmethod
    def auto_detect_streams(cls, data):
        if not isinstance(data, dict):
            return data
        resolved = []
        for raw in data.get("streams", []):
            cls_ = detect_stream_class(raw.get("source", ""))
            resolved.append(cls_(**raw))
        data["streams"] = resolved
        return data


class RunResponse(BaseModel):
    message: str


def detect_stream_class(source: str) -> type["BaseStream"]:
    if RE_CLOUD_FILE.match(source):
        return CloudFileStream
    elif RE_LOCAL_FILE.match(source):
        return LocalFileStream
    elif RE_DATABASE.match(source):
        return DatabaseStream
    else:
        raise ValueError(f"Invalid stream source: {source}")


def s3_to_endpoint_uri(s3_uri: str, endpoint: str, use_ssl: bool = False) -> str:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid S3 URI: {s3_uri}")

    if use_ssl:
        scheme = "https"
    else:
        scheme = "http"

    bucket = parsed.netloc
    path = parsed.path.lstrip("/")

    return f"{scheme}://{endpoint}/{bucket}/{path}"


class PG2S3:
    def __init__(self, config_file: Path | str) -> None:
        self._config_file = config_file
        self._config = self._load_config()
        self._console = rich.console.Console()

    @property
    def config(self) -> Config:
        return self._config

    def _load_config(self) -> Config:
        data = safe_load_file(self._config_file)
        return Config(**data)

    def debug(self, echo: bool = False) -> dict[str, dict[str, str]] | None:
        result = {}

        for name, connection in self._config.connections.items():
            if connection.type == ConnectionType.POSTGRES:
                adapter = PostgresAdapter(connection.settings)
                can_connect = adapter.can_connect()
                result[name] = {
                    "URL": str(adapter.url),
                    "Connection test": can_connect,
                }
            elif connection.type == ConnectionType.S3:
                adapter = S3Adapter(connection.settings)
                can_connect = adapter.can_connect()
                result[name] = {
                    "URL": adapter.url,
                    "Connection test": can_connect,
                }

        if echo:
            for i, item in enumerate(result.items()):
                k1, v1 = item
                self._console.print(f"{'\n' if i > 0 else ''}{k1}:")
                for k2, v2 in v1.items():
                    self._console.print(f"  {k2}: {v2}")

        return result

    def get_connection(self, connection_name: str) -> Connection:
        if connection_name not in self._config.connections:
            raise ConnectionNotFoundException(f"Connection '{connection_name}' not found")

        return self._config.connections[connection_name]

    def get_stream(self, stream_source: str) -> Stream:
        stream = pydash.find(
            self._config.streams,
            lambda stream: f"{stream.source.schema_}.{stream.source.table}" == stream_source,
        )

        if not stream:
            raise StreamNotFoundException(f"Stream '{stream_source}' not found")

        return stream

    def run(
        self, source_connection_name: str, destination_connection_name: str, stream_source: str
    ) -> RunResponse:
        source_connection = self.get_connection(source_connection_name)
        destination_connection = self.get_connection(destination_connection_name)
        stream = self.get_stream(stream_source)

        if source_connection.type != ConnectionType.POSTGRES:
            raise NotImplementedError(f"Source connection type must be '{ConnectionType.POSTGRES}'")

        if destination_connection.type != ConnectionType.S3:
            raise NotImplementedError(f"Destination connection type must be '{ConnectionType.S3}'")

        select = stream.render_stream_select(source_connection)
        columns = stream.list_stream_columns(source_connection)
        columns_str = ", ".join([f"`{column.name}` {column.type}" for column in columns])

        s3_uri = Template(stream.destination).render(
            bucket=destination_connection.settings.bucket,
            database=source_connection.settings.database,
            schema=stream.source.schema_,
            table=stream.source.table,
        )
        s3_endpoint_uri = s3_to_endpoint_uri(
            s3_uri,
            endpoint=destination_connection.settings.endpoint,
            use_ssl=destination_connection.settings.use_ssl,
        )

        sql = """
        CREATE TABLE `{{ table_name }}` ({{ table_columns }})
            ENGINE = S3('{{ s3_endpoint_uri }}', '{{ s3_key_id }}', '{{ s3_secret }}', 'parquet')
            {% if partition_by -%}
            PARTITION BY {{ partition_by }}
            {%- endif %};

        INSERT INTO `{{ table_name }}`
            SELECT * FROM ({{ select }})
            SETTINGS s3_truncate_on_insert = 1;
        """
        sql = Template(sql).render(
            table_name=stream.source.table,
            table_columns=columns_str,
            s3_endpoint_uri=s3_endpoint_uri,
            s3_key_id=destination_connection.settings.key_id,
            s3_secret=destination_connection.settings.secret,
            partition_by=stream.partition_by,
            select=select,
        )

        with session.Session() as sess:
            sess.query(sql)

        prefix = urlparse(s3_uri).path.lstrip("/")
        s3_adapter = S3Adapter(destination_connection.settings)
        objects = s3_adapter.list_objects(prefix=prefix)
        stream_source_identifier = f"{stream.source.schema_}.{stream.source.table}"

        if not objects:
            raise Exception(
                f"Failed to copy table '{stream_source_identifier}' from '{source_connection_name}' to '{destination_connection_name}'"
            )

        return RunResponse(
            message=f"Copied table '{stream_source_identifier}' from '{source_connection_name}' to '{destination_connection_name}'"
        )


def find_config_file() -> Path:
    cwd = os.getcwd()
    config_file = find_up(cwd, "pg2s3.yaml")

    if not config_file:
        raise Exception(f"pg2s3.yaml not found in {cwd} or higher")

    return config_file
