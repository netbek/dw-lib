from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Any


class DbtCommand(StrEnum):
    COMPILE = "compile"
    RUN = "run"
    RUN_OPERATION = "run-operation"
    SEED = "seed"


class DbtResourceType(StrEnum):
    MODEL = "model"
    SEED = "seed"
    SOURCE = "source"


class DbtColumnMeta(BaseModel):
    sqlalchemy_type: str


class DbtColumn(BaseModel):
    data_type: str
    meta: DbtColumnMeta | None = None
    name: str


class DbtContract(BaseModel):
    alias_types: bool
    enforced: bool


class DbtDependsOn(BaseModel):
    macros: list[str] | None = None
    nodes: list[str] | None = None


class DbtDocs(BaseModel):
    node_color: str | None = None
    show: bool


class DbtPersistDocs(BaseModel):
    columns: bool | None = None


class DbtTableMeta(BaseModel):
    python_class: str


class DbtTable(BaseModel):
    columns: list[DbtColumn] | None = None
    loaded_at_field: str | None = None
    meta: DbtTableMeta | None = None
    name: str


class DbtBaseResource(BaseModel):
    name: str
    original_file_path: str
    package_name: str
    resource_type: DbtResourceType
    tags: list[str]
    unique_id: str


class DbtModelConfig(BaseModel):
    access: str
    alias: str | None = None
    batch_filter: str | None = None
    batch_size: int | None = None
    column_types: dict[str, str]
    contract: DbtContract
    database: str | None = None
    docs: DbtDocs
    enabled: bool
    engine: str | None = None
    full_refresh: bool | None = False
    grants: dict[str, list[str]]
    group: str | None = None
    incremental_strategy: str | None = None
    materialized: str
    meta: dict[str, str | int | float | bool | list[dict] | None]
    on_configuration_change: str
    on_schema_change: str
    order_by: str | None = None
    packages: list[str]
    persist_docs: DbtPersistDocs
    post_hook: list[str] | None = None
    pre_hook: list[str] | None = None
    quoting: dict[str, bool]
    range_max: str | None = None
    range_min: str | None = None
    schema_: str | None = Field(default=None, serialization_alias="schema")
    tags: list[str]
    unique_key: str | None = None


class DbtModelColumnConfig(BaseModel):
    meta: dict[str, Any] = {}
    tags: list[str] = []


class DbtModelColumn(BaseModel):
    config: DbtModelColumnConfig
    constraints: list[Any] = []
    data_type: str
    description: str = ""
    doc_blocks: list[Any] = []
    granularity: int | None = None
    meta: dict[str, Any] = {}
    name: str
    quote: bool | None = None
    tags: list[str] = []


class DbtModel(DbtBaseResource):
    alias: str
    columns: dict[str, DbtModelColumn]
    config: DbtModelConfig
    depends_on: DbtDependsOn
    description: str = ""


class DbtSeedConfig(BaseModel):
    alias: str | None = None
    column_types: dict[str, str]
    contract: DbtContract
    database: str | None = None
    delimiter: str
    description: str = ""
    docs: DbtDocs
    enabled: bool
    full_refresh: bool | None = False
    grants: dict[str, list[str]]
    group: str | None = None
    incremental_strategy: str | None = None
    materialized: str
    meta: dict[str, str | int | float | bool | None]
    on_configuration_change: str
    on_schema_change: str
    packages: list[str]
    persist_docs: DbtPersistDocs
    post_hook: list[str] | None = None
    pre_hook: list[str] | None = None
    quote_columns: bool | None = None
    quoting: dict[str, bool]
    schema_: str | None = Field(default=None, serialization_alias="schema")
    tags: list[str]
    unique_key: str | None = None


class DbtSeed(DbtBaseResource):
    alias: str
    config: DbtSeedConfig
    depends_on: DbtDependsOn


class DbtSourceConfig(BaseModel):
    enabled: bool


class DbtSource(DbtBaseResource):
    config: DbtSourceConfig
    original_config: DbtTable | None = None
    source_name: str
