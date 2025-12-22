from .constants import CODEGEN_TO_CLICKHOUSE_DATA_TYPE
from .database.adapters import ClickHouseAdapter
from .typing import ClickHouseSettings
from .utils.filesystem import find_up, get_file_extension
from .utils.python_utils import is_python_keyword
from .utils.sqlmodel_utils import parse_create_table_statement
from .utils.yaml_utils import safe_load_file
from dbt.cli.main import dbtRunner, dbtRunnerResult
from enum import StrEnum
from livereload import Server
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any

import json
import os
import pydash
import subprocess
import yaml


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
    meta: dict[str, str | int | float | bool | None]
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


class DbtModel(DbtBaseResource):
    alias: str
    config: DbtModelConfig
    depends_on: DbtDependsOn


class DbtSeedConfig(BaseModel):
    alias: str | None = None
    column_types: dict[str, str]
    contract: DbtContract
    database: str | None = None
    delimiter: str
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


RE_REF = r"^ref\(['\"](.*?)['\"]\)$"
RE_SOURCE = r"^source\(['\"](.*?)['\"], ['\"](.*?)['\"]\)$"

RESOURCE_TYPE_TO_CLASS = {
    DbtResourceType.MODEL: DbtModel,
    DbtResourceType.SEED: DbtSeed,
    DbtResourceType.SOURCE: DbtSource,
}

INDENT = pydash.repeat(" ", 4)


def serialize_dict(data: dict) -> str:
    return ", ".join(f"{key}={value}" for key, value in data.items())


def to_field_name(column_name: str) -> str:
    return column_name.lstrip("_")


def get_class_import_string(class_) -> str | None:
    if class_.__module__ == "builtins":
        return None
    elif class_.__module__ in ["datetime"]:
        return "import datetime"
    else:
        return f"from {class_.__module__} import {class_.__name__}"


def create_class_filename(class_name: str) -> str:
    filename = pydash.snake_case(class_name)

    # Fix keywords
    if is_python_keyword(filename):
        filename = filename + "_"

    return filename


def create_factory_name(model_name: str) -> str:
    return f"{model_name}Factory"


def create_model_code(
    db_settings: ClickHouseSettings,
    database: str,
    dbt_resource: DbtSource,
    extend_primary_key: bool | None = False,
    random_seed: int = 0,
) -> dict[str, str]:
    """Create the code of a SQLModel class from a table statement."""
    # 1. Create model
    clickhouse_adapter = ClickHouseAdapter(db_settings)
    table_name = dbt_resource.name
    model_name = dbt_resource.original_config.meta.python_class
    statement = clickhouse_adapter.get_create_table_statement(table_name, database=database)
    parsed_statement = parse_create_table_statement(statement)
    table_kwargs = {"schema": database}
    engine = parsed_statement["engine"]
    engine_kwargs = {}

    if parsed_statement["version"]:
        engine_kwargs["version"] = f"'{parsed_statement['version']}'"

    if parsed_statement["order_by"]:
        engine_kwargs["order_by"] = tuple(parsed_statement["order_by"])

    if parsed_statement["primary_key"]:
        engine_kwargs["primary_key"] = tuple(parsed_statement["primary_key"])

    if parsed_statement["settings"]:
        engine_kwargs.update(parsed_statement["settings"])

    imports = [
        "from clickhouse_sqlalchemy import engines",
        "from dw_lib.polyfactory.mixins import BaseMixin",
        "from dw_lib.sqlalchemy.clickhouse import types",
        "from sqlmodel import Column, Field, SQLModel",
    ]

    columns = []

    for column in parsed_statement["columns"]:
        dbt_column = pydash.find(
            dbt_resource.original_config.columns, lambda c: c.name == column["name"]
        )
        field_name = to_field_name(column["name"])

        if dbt_column and dbt_column.meta and dbt_column.meta.sqlalchemy_type:
            sqlalchemy_type = dbt_column.meta.sqlalchemy_type
        else:
            sqlalchemy_type = column["sqlalchemy_type"]

        sqlalchemy_column_kwargs = {
            "name": f"'{column['name']}'",
            "type_": sqlalchemy_type,
        }

        # ClickHouse does not require a unique primary key, but SQLAlchemy does. To work around
        # this, flag the _peerdb_version column as part of a composite primary key in SQLAlchemy.
        is_sqlalchemy_primary_key = column["primary_key"] or (
            extend_primary_key and column["name"] == "_peerdb_version"
        )

        if is_sqlalchemy_primary_key:
            sqlalchemy_column_kwargs["primary_key"] = True

        if not is_sqlalchemy_primary_key:
            sqlalchemy_column_kwargs["nullable"] = column["nullable"]

        field_kwargs = {
            "sa_column": f"Column({serialize_dict(sqlalchemy_column_kwargs)})",
        }

        column_def = (
            f"{field_name}: {column['pydantic_type']} = Field({serialize_dict(field_kwargs)})"
        )
        columns.append(column_def)

        class_import = get_class_import_string(column["python_type"])
        if class_import:
            imports.append(class_import)

    lines = []

    # Add table class
    lines.append(f"class {model_name}(BaseMixin, SQLModel, table=True):")
    lines.append(INDENT + f"__tablename__ = '{table_name}'")
    lines.append(
        INDENT
        + f"__table_args__ = (engines.{engine}({serialize_dict(engine_kwargs)}), {table_kwargs},)"
    )
    lines.append("")

    # Add columns
    for column in columns:
        lines.append(INDENT + column)

    # Add statement for reference, add imports
    imports = sorted(list(set(imports)))
    lines = ['"""\nCreated from:\n\n' + statement + '\n"""', ""] + imports + ["", ""] + lines

    model_code = "\n".join(lines) + "\n"

    # 2. Create factory
    model_filename = create_class_filename(model_name)
    factory_name = create_factory_name(model_name)

    imports = [
        f"from .{model_filename} import {model_name}",
        "from dw_lib.polyfactory.factories.sqlmodel_factory import SQLModelFactory",
        "from dw_lib.polyfactory.mixins import PeerDBFactoryMixin",
    ]

    lines = []

    # Add factory class
    lines.append(f"class {factory_name}(PeerDBFactoryMixin, SQLModelFactory[{model_name}]):")
    lines.append(INDENT + f"__random_seed__ = {random_seed}")

    for column in parsed_statement["columns"]:
        # If the column is an integer primary key, then generate a globally unique integer
        if column["python_type"] is int and column["primary_key"]:
            lines.append("")
            lines.append(INDENT + "@classmethod")
            lines.append(INDENT + f"def {column['name']}(cls) -> int:")
            lines.append(INDENT + INDENT + "return int(pydash.unique_id())")

            imports.append("import pydash")

    # Add imports
    imports = sorted(list(set(imports)))
    lines = imports + ["", ""] + lines

    factory_code = "\n".join(lines) + "\n"

    return {
        "model_code": model_code,
        "factory_code": factory_code,
    }


def create_model_file(
    db_settings: ClickHouseSettings,
    database: str,
    dbt_resource: DbtSource,
    directory: str,
    extend_primary_key: bool | None = False,
    replace_model: bool | None = False,
    replace_factory: bool | None = False,
) -> None:
    model_name = dbt_resource.original_config.meta.python_class
    model_filename = create_class_filename(model_name)
    model_path = os.path.join(directory, f"{model_filename}.py")
    create_model = not os.path.exists(model_path) or replace_model

    factory_name = create_factory_name(model_name)
    factory_filename = create_class_filename(factory_name)
    factory_path = os.path.join(directory, f"{factory_filename}.py")
    create_factory = not os.path.exists(factory_path) or replace_factory

    if create_model or create_factory:
        result = create_model_code(
            db_settings, database, dbt_resource, extend_primary_key=extend_primary_key
        )

        if create_model:
            with open(model_path, "w") as fp:
                fp.write(result["model_code"])

        if create_factory:
            with open(factory_path, "w") as fp:
                fp.write(result["factory_code"])


def create_init_file(dbt_resources: list[DbtSource], directory: str) -> None:
    file_path = os.path.join(directory, "__init__.py")
    all = []
    imports = []

    for dbt_resource in dbt_resources:
        class_name = dbt_resource.original_config.meta.python_class

        model_filename = create_class_filename(class_name)
        all.append(class_name)
        imports.append(f"from .{model_filename} import {class_name}")

        factory_name = create_factory_name(class_name)
        factory_filename = create_class_filename(factory_name)
        all.append(factory_name)
        imports.append(f"from .{factory_filename} import {factory_name}")

    lines = [f"__all__ = {all}", "", "\n".join(imports), ""]
    code = "\n".join(lines)

    with open(file_path, "w") as fp:
        fp.write(code)


def get_profiles_dir() -> Path:
    dbt_profiles_dir = os.environ.get("DBT_PROFILES_DIR")

    if dbt_profiles_dir:
        return Path(dbt_profiles_dir)

    return Path.home() / ".dbt"


def find_project_config_file() -> Path:
    cwd = os.getcwd()
    project_config_file = find_up(cwd, "dbt_project.yml")

    if not project_config_file:
        raise Exception(f"dbt_project.yml not found in {cwd} or higher")

    return project_config_file


def find_project_dir() -> Path:
    return find_project_config_file().parent


def resolve_resource_path(project_dir: Path, resource: dict) -> Path | None:
    project_name = project_dir.name

    if resource["package_name"] == project_name:
        path = project_dir / resource["original_file_path"]
    else:
        path = project_dir / "dbt_packages" / resource["original_file_path"]

    if path.exists():
        return path


def bundle_docs(project_dir: Path, dest_dir: Path | None = None) -> Path:
    """
    Transform output from `dbt docs generate` into a single HTML file.

    Source: https://data-banana.github.io/dbt-generate-doc-in-one-static-html-file.html
    """
    if dest_dir is None:
        dest_dir = project_dir / "docs"

    target_dir = project_dir / "target"
    html_file = target_dir / "index.html"
    manifest_file = target_dir / "manifest.json"
    catalog_file = target_dir / "catalog.json"
    dest_file = dest_dir / "index.html"

    with open(html_file) as fp:
        html = fp.read()

    with open(manifest_file) as fp:
        manifest = json.load(fp)

    with open(catalog_file) as fp:
        catalog = json.load(fp)

    search_str = 'n = [o("manifest", "manifest.json" + t), o("catalog", "catalog.json" + t)]'
    replace_str = (
        "n=[{label: 'manifest', data: "
        + json.dumps(manifest)
        + "},{label: 'catalog', data: "
        + json.dumps(catalog)
        + "}]"
    )
    html = html.replace(search_str, replace_str)

    os.makedirs(dest_file.parent, exist_ok=True)
    with open(dest_file, "w") as fp:
        fp.write(html)

    return dest_file


class Dbt:
    def __init__(self, project_dir: Path, target: str | None = None) -> None:
        self._profiles_dir = get_profiles_dir()
        self._project_dir = project_dir
        self._project_docs_dir = self._project_dir / "docs"
        self._project_config_file = self._project_dir / "dbt_project.yml"
        self._target = target

    def list_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        models: str | None = None,
        output: str | None = None,
        quiet: bool | None = False,
        resource_types: list[DbtResourceType] | None = None,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "list",
            "--profiles-dir",
            str(self._profiles_dir),
            "--project-dir",
            str(self._project_dir),
        ]

        if debug:
            cmd.extend(["--debug"])
        else:
            cmd.extend(["--no-debug"])

        if exclude:
            cmd.extend(["--exclude", exclude])

        if fail_fast:
            cmd.extend(["--fail-fast"])
        else:
            cmd.extend(["--no-fail-fast"])

        if models:
            cmd.extend(["--models", models])

        if output:
            cmd.extend(["--output", output])

        if quiet:
            cmd.extend(["--quiet"])
        else:
            cmd.extend(["--no-quiet"])

        if resource_types:
            for resource_type in resource_types:
                cmd.extend(["--resource-type", resource_type])

        if select:
            cmd.extend(["--select", select])

        if selector:
            cmd.extend(["--selector", selector])

        if target:
            cmd.extend(["--target", target])

        if use_colors:
            cmd.extend(["--use-colors"])
        else:
            cmd.extend(["--no-use-colors"])

        if vars:
            vars_yaml = yaml.safe_dump(vars, default_flow_style=False)
            cmd.extend(["--vars", vars_yaml])

        return cmd

    def list_(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        models: str | None = None,
        output: str | None = None,
        quiet: bool | None = False,
        resource_types: list[DbtResourceType] | None = None,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> dbtRunnerResult:
        cmd = self.list_command(
            debug=debug,
            exclude=exclude,
            fail_fast=fail_fast,
            models=models,
            output=output,
            quiet=quiet,
            resource_types=resource_types,
            select=select,
            selector=selector,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )

        return dbtRunner().invoke(cmd[1:])

    def get_resource(self, name: str) -> DbtModel | DbtSeed | DbtSource | None:
        resources = self.list_resources(select=name)

        if not resources:
            return None

        return resources[0]

    def list_resources(
        self,
        resource_types: list[DbtResourceType] | None = None,
        select: str | None = None,
    ) -> list[DbtModel | DbtSeed | DbtSource]:
        valid_resource_types = RESOURCE_TYPE_TO_CLASS.keys()

        if resource_types is None:
            resource_types = valid_resource_types

        for resource_type in resource_types:
            if resource_type not in valid_resource_types:
                raise ValueError(
                    f"'resource_types' must be any of: {', '.join(valid_resource_types)}"
                )

        result = self.list_(
            output="json",
            quiet=True,
            resource_types=resource_types,
            select=select,
        )
        resource_dicts = [json.loads(string) for string in result.result]

        cache = {}
        for resource in resource_dicts:
            if resource["resource_type"] == DbtResourceType.SOURCE:
                original_config = None
                path = resolve_resource_path(self._project_dir, resource)

                if path and get_file_extension(path) in [".yml", ".yaml"]:
                    if path not in cache:
                        cache[path] = safe_load_file(path)

                    for source in cache[path]["sources"]:
                        if source["name"] == resource["source_name"]:
                            for table in source["tables"]:
                                if table["name"] == resource["name"]:
                                    original_config = table
                                    break
                        if original_config:
                            break

                resource["original_config"] = original_config

        resources = []
        for resource in resource_dicts:
            class_ = RESOURCE_TYPE_TO_CLASS[resource["resource_type"]]
            resources.append(class_(**resource))

        return resources

    def run_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        full_refresh: bool | None = False,
        models: str | None = None,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "run",
            "--profiles-dir",
            str(self._profiles_dir),
            "--project-dir",
            str(self._project_dir),
        ]

        if debug:
            cmd.extend(["--debug"])
        else:
            cmd.extend(["--no-debug"])

        if exclude:
            cmd.extend(["--exclude", exclude])

        if fail_fast:
            cmd.extend(["--fail-fast"])
        else:
            cmd.extend(["--no-fail-fast"])

        if full_refresh:
            cmd.extend(["--full-refresh"])

        if models:
            cmd.extend(["--models", models])

        if quiet:
            cmd.extend(["--quiet"])
        else:
            cmd.extend(["--no-quiet"])

        if select:
            cmd.extend(["--select", select])

        if selector:
            cmd.extend(["--selector", selector])

        if target:
            cmd.extend(["--target", target])

        if use_colors:
            cmd.extend(["--use-colors"])
        else:
            cmd.extend(["--no-use-colors"])

        if vars:
            cmd.extend(["--vars", f"'{json.dumps(vars)}'"])

        return cmd

    def run(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        full_refresh: bool | None = False,
        models: str | None = None,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> dbtRunnerResult:
        cmd = self.run_command(
            debug=debug,
            fail_fast=fail_fast,
            full_refresh=full_refresh,
            exclude=exclude,
            models=models,
            quiet=quiet,
            select=select,
            selector=selector,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )

        return dbtRunner().invoke(cmd[1:])

    def run_operation_command(
        self,
        macro: str,
        args: dict[str, Any] | None = None,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "run-operation",
            "--profiles-dir",
            str(self._profiles_dir),
            "--project-dir",
            str(self._project_dir),
            macro,
        ]

        if args:
            cmd.extend(["--args", json.dumps(args)])

        if debug:
            cmd.extend(["--debug"])
        else:
            cmd.extend(["--no-debug"])

        if fail_fast:
            cmd.extend(["--fail-fast"])
        else:
            cmd.extend(["--no-fail-fast"])

        if quiet:
            cmd.extend(["--quiet"])
        else:
            cmd.extend(["--no-quiet"])

        if target:
            cmd.extend(["--target", target])

        if use_colors:
            cmd.extend(["--use-colors"])
        else:
            cmd.extend(["--no-use-colors"])

        if vars:
            cmd.extend(["--vars", f"'{json.dumps(vars)}'"])

        return cmd

    def run_operation(
        self,
        macro: str,
        args: dict[str, Any] | None = None,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> dbtRunnerResult:
        cmd = self.run_operation_command(
            macro,
            args=args,
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )

        return dbtRunner().invoke(cmd[1:])

    def seed_command(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
    ) -> list[str]:
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "seed",
            "--profiles-dir",
            str(self._profiles_dir),
            "--project-dir",
            str(self._project_dir),
        ]

        if debug:
            cmd.extend(["--debug"])
        else:
            cmd.extend(["--no-debug"])

        if fail_fast:
            cmd.extend(["--fail-fast"])
        else:
            cmd.extend(["--no-fail-fast"])

        if quiet:
            cmd.extend(["--quiet"])
        else:
            cmd.extend(["--no-quiet"])

        if select:
            cmd.extend(["--select", select])

        if target:
            cmd.extend(["--target", target])

        if use_colors:
            cmd.extend(["--use-colors"])
        else:
            cmd.extend(["--no-use-colors"])

        return cmd

    def seed(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
    ) -> dbtRunnerResult:
        cmd = self.seed_command(
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            select=select,
            target=target,
            use_colors=use_colors,
        )

        return dbtRunner().invoke(cmd[1:])

    def generate_model_yaml(self, models: list[str]):
        """Generate the schema YAML for the given models using dbt-codegen."""
        resources = self.list_resources(resource_types=[DbtResourceType.MODEL])
        selected_resources = pydash.filter_(resources, lambda resource: resource.name in models)

        # Build the models
        model_names = [resource.name for resource in selected_resources]
        self.run(quiet=True, full_refresh=True, models=" ".join(model_names))

        # Generate the schema YAML
        cmd = self.run_operation_command(
            "generate_model_yaml", quiet=True, args={"model_names": model_names}
        )
        output = subprocess.check_output(cmd, cwd=self._project_dir).decode().strip()
        new_models = yaml.safe_load(output)["models"]

        for resource in selected_resources:
            model_name = resource.name
            model_path = self._project_dir / resource.original_file_path
            schema_path = model_path.parent / f"{model_name}.yml"
            schema_dir = schema_path.parent
            new_model = pydash.find(new_models, lambda model: model["name"] == model_name)

            if not new_model:
                continue

            os.makedirs(schema_dir, exist_ok=True)

            # Load existing schema
            if schema_path.exists():
                schema = safe_load_file(schema_path)
            else:
                schema = {"version": 2, "models": []}

            new_model = {
                "name": new_model["name"],
                "columns": [
                    {
                        "name": column["name"],
                        "data_type": CODEGEN_TO_CLICKHOUSE_DATA_TYPE.get(
                            column["data_type"], column["data_type"]
                        ),
                    }
                    for column in new_model["columns"]
                ],
            }
            old_model_indexes = [
                i for i, model in enumerate(schema["models"]) if model["name"] == model_name
            ]

            if old_model_indexes:
                schema["models"][old_model_indexes[0]] = new_model
            else:
                schema["models"].append(new_model)

            schema["models"] = sorted(schema["models"], key=lambda model: model["name"])

            # Write schema file
            with open(schema_path, "w") as fp:
                data = yaml.safe_dump(schema, sort_keys=False)
                fp.write(data)

    def docs_generate_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        models: str | None = None,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "docs",
            "generate",
            "--profiles-dir",
            str(self._profiles_dir),
            "--project-dir",
            str(self._project_dir),
        ]

        if debug:
            cmd.extend(["--debug"])
        else:
            cmd.extend(["--no-debug"])

        if exclude:
            cmd.extend(["--exclude", exclude])

        if fail_fast:
            cmd.extend(["--fail-fast"])
        else:
            cmd.extend(["--no-fail-fast"])

        if models:
            cmd.extend(["--models", models])

        if quiet:
            cmd.extend(["--quiet"])
        else:
            cmd.extend(["--no-quiet"])

        if select:
            cmd.extend(["--select", select])

        if selector:
            cmd.extend(["--selector", selector])

        if target:
            cmd.extend(["--target", target])

        if use_colors:
            cmd.extend(["--use-colors"])
        else:
            cmd.extend(["--no-use-colors"])

        if vars:
            cmd.extend(["--vars", f"'{json.dumps(vars)}'"])

        return cmd

    def docs_generate(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        models: str | None = None,
        quiet: bool | None = True,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> tuple[dbtRunnerResult, Path]:
        cmd = self.docs_generate_command(
            debug=debug,
            fail_fast=fail_fast,
            exclude=exclude,
            models=models,
            quiet=quiet,
            select=select,
            selector=selector,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )
        result = dbtRunner().invoke(cmd[1:])
        dest_file = bundle_docs(self._project_dir)

        return (result, dest_file)

    def docs_serve(self):
        project_config = safe_load_file(self._project_dir / "dbt_project.yml")

        # If the docs page has not been generated before, then do so now
        if not os.path.exists(os.path.join(self._project_docs_dir, "index.html")):
            self.docs_generate()

        watch_paths = [self._project_config_file]
        for path in project_config["macro-paths"]:
            watch_paths.extend(
                [
                    os.path.join(self._project_dir, path, "**", "*.sql"),
                ]
            )
        for path in project_config["model-paths"]:
            watch_paths.extend(
                [
                    os.path.join(self._project_dir, path, "**", "*.sql"),
                    os.path.join(self._project_dir, path, "**", "*.yml"),
                ]
            )

        # Start the LiveReload server
        server = Server()
        for path in watch_paths:
            server.watch(path, lambda: self.docs_generate())
        server.serve(host="0.0.0.0", port=8080, root=self._project_docs_dir)
