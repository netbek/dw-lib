from pathlib import Path
from pydantic import BaseModel
from pydantic import ClickHouseDsn as _ClickHouseDsn
from pydantic import HttpUrl as _HttpUrl
from pydantic import TypeAdapter, UrlConstraints
from urllib.parse import urljoin, urlparse, urlunparse

import re


# TODO Remove this class in favour of ClickHouseDsn after "clickhousedb+connect" has been added
class ClickHouseDsn(_ClickHouseDsn):
    _constraints = UrlConstraints(
        allowed_schemes=_ClickHouseDsn._constraints.allowed_schemes + ["clickhousedb+connect"],
        default_host=_ClickHouseDsn._constraints.default_host,
        default_port=_ClickHouseDsn._constraints.default_port,
    )


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


class DbtSettings(BaseModel):
    directory: Path | str
    config: dict


class PeerDBSettings(BaseModel):
    config_path: Path | str


class NotebookSettings(BaseModel):
    directory: Path | str


class ColumnStats(BaseModel):
    name: str
    data_type: str
    nullable: bool | None = None
    cardinality: int
    null_count: int
    null_pct: float


class TableStats(BaseModel):
    columns: list[ColumnStats]

    @property
    def columns_sorted_by_cardinality(self) -> list[ColumnStats]:
        return sorted(self.columns, key=lambda x: (x.cardinality, x.name))
