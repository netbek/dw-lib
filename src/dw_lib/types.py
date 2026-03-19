from dw_lib.utils.python_utils import (
    validate_pydantic_clickhouse_dsn,
    validate_pydantic_postgres_dsn,
)
from pathlib import Path
from pydantic import (
    BaseModel,
    ClickHouseDsn,
    ConfigDict,
    Field,
    field_validator,
)
from pydantic import HttpUrl as _HttpUrl
from pydantic import (
    model_validator,
    PostgresDsn,
    TypeAdapter,
)
from sqlalchemy.engine import make_url, URL
from sqlglot import exp, parse_one
from sqlglot.dialects.dialect import Dialects, DialectType
from typing import ClassVar, Literal, Self
from urllib.parse import urljoin, urlparse, urlunparse

import math
import psutil
import re


class HttpUrl(_HttpUrl):
    def join(self, path: str) -> "HttpUrl":
        """Return a HttpUrl, using this URL as the base."""
        base = str(self)

        # Ensure base behaves like a directory
        if not base.endswith("/"):
            base = base + "/"

        parsed_path = urlparse(path)

        # Normalize the path:
        # 1. Remove leading slashes (avoid network-location override)
        # 2. Collapse multiple slashes into one
        normalized_path = (parsed_path.netloc + "/" + parsed_path.path).strip("/")
        normalized_path = re.sub(r"/+", "/", normalized_path)

        # Reconstruct the relative URL (path + query + fragment)
        normalized_path = urlunparse(
            ("", "", normalized_path, parsed_path.params, parsed_path.query, parsed_path.fragment)
        )

        url_str = urljoin(base, normalized_path)

        return TypeAdapter(HttpUrl).validate_python(url_str)


class BaseRelation(BaseModel):
    dialect: ClassVar[DialectType] = ""

    @classmethod
    def _parse_to_parts(cls, identifier: str) -> list[str]:
        if identifier:
            expression = parse_one(identifier, read=cls.dialect, into=exp.Table)

            if isinstance(expression.this, exp.Identifier):
                parts = [expression.catalog, expression.db, expression.this.name]
            else:
                parts = [expression.this]

            return [part for part in parts if part]
        else:
            raise ValueError(f"Invalid table identifier: {identifier}")


class ClickHouseRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.CLICKHOUSE
    database: str | None = Field(default=None)
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> Self:
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 2:
            return cls(database=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


class PostgresRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.POSTGRES
    database: str | None = Field(default=None)
    schema_: str | None = Field(default=None, serialization_alias="schema")
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> Self:
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 3:
            return cls(database=parts[0], schema_=parts[1], table=parts[2])
        elif len(parts) == 2:
            return cls(schema_=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.schema_) if self.schema_ else None,
            catalog=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


class DuckDBRelation(BaseRelation):
    dialect: ClassVar[DialectType] = Dialects.DUCKDB
    database: str | None = Field(default=None)
    schema_: str | None = Field(default=None, serialization_alias="schema")
    table: str

    @classmethod
    def from_string(cls, identifier: str) -> Self:
        parts = cls._parse_to_parts(identifier)
        if len(parts) == 3:
            return cls(database=parts[0], schema_=parts[1], table=parts[2])
        elif len(parts) == 2:
            return cls(schema_=parts[0], table=parts[1])
        return cls(table=parts[0])

    def __str__(self) -> str:
        table_expr = exp.Table(
            this=exp.to_identifier(self.table),
            db=exp.to_identifier(self.schema_) if self.schema_ else None,
            catalog=exp.to_identifier(self.database) if self.database else None,
        )
        return table_expr.sql(dialect=self.dialect)


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


class ClickHouseSettings(BaseModel):
    host: str
    http_port: int | None = None
    tcp_port: int | None = None
    username: str
    password: str
    database: str
    driver: Literal["http", "native"] = "http"

    @classmethod
    def from_url(cls, url: ClickHouseDsn | URL | str) -> Self:
        if isinstance(url, ClickHouseDsn):
            _url = make_url(str(url))
        elif isinstance(url, URL):
            validate_pydantic_clickhouse_dsn(url.render_as_string(hide_password=False))
            _url = url
        elif isinstance(url, str):
            validate_pydantic_clickhouse_dsn(url)
            _url = make_url(url)
        else:
            raise TypeError("url must be one of: Pydantic ClickHouseDsn, SQLAlchemy URL, str")

        given_driver = None
        if _url.drivername and "+" in _url.drivername:
            given_driver = _url.drivername.split("+")[1]

        given_port = _url.port

        if given_driver in ["http", "native"]:
            driver = given_driver
        elif given_port == 9000:
            driver = "native"
        else:
            driver = "http"

        http_port = given_port if driver == "http" else None
        tcp_port = given_port if driver == "native" else None

        return cls(
            host=_url.host,
            http_port=http_port,
            tcp_port=tcp_port,
            username=_url.username,
            password=_url.password,
            database=_url.database,
            driver=driver,
        )

    @model_validator(mode="after")
    def validate_ports_and_driver(self) -> Self:
        if self.http_port is None and self.tcp_port is None:
            raise ValueError("At least one of http_port or tcp_port must be provided")

        if self.driver == "http" and self.http_port is None:
            raise ValueError("Driver set to 'http' but http_port is missing")

        if self.driver == "native" and self.tcp_port is None:
            raise ValueError("Driver set to 'native' but tcp_port is missing")

        return self

    def to_sqlalchemy_url(self) -> URL:
        if self.driver == "native":
            port = self.tcp_port
        else:
            port = self.http_port

        return URL.create(
            f"clickhouse+{self.driver}",
            host=self.host,
            port=port,
            username=self.username,
            password=self.password,
            database=self.database,
        )

    def to_string(self, hide_password: bool = True) -> str:
        return self.to_sqlalchemy_url().render_as_string(hide_password=hide_password)

    def __str__(self) -> str:
        return self.to_string()


class DuckDBSettings(BaseModel):
    database: Path | str
    schema_: str = Field(default="main", serialization_alias="schema")
    extensions: list[str] | None = None
    settings: DuckDBSystemSettings | None = None

    @classmethod
    def from_url(cls, url: URL | str) -> Self:
        url = make_url(url)

        return cls(database=url.database)

    def to_sqlalchemy_url(self) -> URL:
        return URL.create("duckdb", database=str(self.database))

    def to_string(self, hide_password: bool = True) -> str:
        return self.to_sqlalchemy_url().render_as_string(hide_password=hide_password)

    def __str__(self) -> str:
        return self.to_string()


class PostgresSettings(BaseModel):
    host: str
    port: int
    username: str
    password: str
    database: str
    schema_: str = Field(default="public", serialization_alias="schema")
    driver: Literal["psycopg", "psycopg2"] = "psycopg2"

    @classmethod
    def from_url(cls, url: PostgresDsn | URL | str) -> Self:
        if isinstance(url, PostgresDsn):
            _url = make_url(str(url))
        elif isinstance(url, URL):
            validate_pydantic_postgres_dsn(url.render_as_string(hide_password=False))
            _url = url
        elif isinstance(url, str):
            validate_pydantic_postgres_dsn(url)
            _url = make_url(url)
        else:
            raise TypeError("url must be one of: Pydantic PostgresDsn, SQLAlchemy URL, str")

        given_driver = None
        if _url.drivername and "+" in _url.drivername:
            given_driver = _url.drivername.split("+")[1]

        if given_driver in ["psycopg", "psycopg2"]:
            driver = given_driver
        else:
            driver = "psycopg2"

        return cls(
            host=_url.host,
            port=_url.port,
            username=_url.username,
            password=_url.password,
            database=_url.database,
            driver=driver,
        )

    def to_sqlalchemy_url(self) -> URL:
        return URL.create(
            f"postgresql+{self.driver}",
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database=self.database,
        )

    def to_string(self, hide_password: bool = True) -> str:
        return self.to_sqlalchemy_url().render_as_string(hide_password=hide_password)

    def __str__(self) -> str:
        return self.to_string()


class S3Settings(BaseModel):
    key_id: str
    secret: str
    region: str
    endpoint: str
    use_ssl: bool
    url_style: str = "path"
    bucket: str
    prefix: str | None = None


class DbtSettings(BaseModel):
    directory: Path | str
    config: dict


class PeerDBSettings(BaseModel):
    config_path: Path | str


class NotebookSettings(BaseModel):
    directory: Path | str
