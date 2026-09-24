from .types import (
    DbtCommand,
    DbtDocsGenerateResult,
    DbtInvocationResult,
    DbtModel,
    DbtResourceType,
    DbtSeed,
)
from clickhouse_connect.driver.client import Client
from dbt.artifacts.schemas.results import RunStatus
from dbt.cli.main import dbtRunner, dbtRunnerResult
from dbt.contracts.graph.nodes import ModelNode
from dbt_common.events.base_types import EventMsg
from dw_lib.database import ClickHouseAdapter, parse_create_table_statement
from dw_lib.exceptions import (
    ConfigFileNotFoundException,
    DbtManifestNotFoundException,
    UnsupportedCommandException,
    UnsupportedRunStatusException,
)
from dw_lib.utils.filesystem import find_up
from functools import cached_property
from io import StringIO
from livereload import Server
from opentelemetry import trace
from pathlib import Path
from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from typing import Any
from uuid import uuid4

import datetime
import json
import os
import pydash
import shlex

RESOURCE_TYPE_TO_CLASS = {
    DbtResourceType.MODEL: DbtModel,
    DbtResourceType.SEED: DbtSeed,
}


def _invoke(cmd: list[str], capture_events: bool) -> tuple[dbtRunnerResult, list[EventMsg]]:
    """Invoke a dbt command, optionally capturing dbt events.

    Args:
        cmd (list[str]): Full command argv starting with `"dbt"`. Only
            `cmd[1:]` is passed to `dbtRunner.invoke`.
        capture_events (bool): If True, register an event callback so dbt
            events (EventMsg) are collected during the invocation. The dbt
            file logger runs in both modes.

    Returns:
        tuple[dbtRunnerResult, list[EventMsg]]: The runner result and the
            captured events in fire order (`[]` when `capture_events` is False).
    """
    if not capture_events:
        return dbtRunner().invoke(cmd[1:]), []
    events: list[EventMsg] = []
    return dbtRunner(callbacks=[events.append]).invoke(cmd[1:]), events


def find_profiles_dir() -> Path:
    """Find the dbt profiles directory.

    Returns:
        Path: The `DBT_PROFILES_DIR` environment variable when set,
            otherwise `~/.dbt`.
    """
    dbt_profiles_dir = os.environ.get("DBT_PROFILES_DIR")

    if dbt_profiles_dir:
        return Path(dbt_profiles_dir)

    return Path.home() / ".dbt"


def find_project_config_file() -> Path:
    """Find the `dbt_project.yml` config file.

    Searches upward from the `DBT_PROJECT_DIR` environment variable when set,
    otherwise from the current working directory.

    Returns:
        Path: The located `dbt_project.yml` file.

    Raises:
        ConfigFileNotFoundException: If no `dbt_project.yml` is found.
    """
    dbt_project_dir = os.environ.get("DBT_PROJECT_DIR")

    if dbt_project_dir:
        cwd = Path(dbt_project_dir)
    else:
        cwd = os.getcwd()

    project_config_file = find_up(cwd, "dbt_project.yml")

    if not project_config_file:
        raise ConfigFileNotFoundException(f"dbt_project.yml not found in {cwd} or higher")

    return project_config_file


def find_project_dir() -> Path:
    """Find the dbt project directory.

    Returns:
        Path: The parent directory of the located `dbt_project.yml` file.
    """
    return find_project_config_file().parent


def resolve_resource_path(project_dir: Path, resource: dict) -> Path | None:
    """Resolve the filesystem path of a manifest resource.

    Args:
        project_dir (Path): The dbt project directory.
        resource (dict): A manifest node dict with `package_name` and
            `original_file_path` keys. Resources from the project itself
            resolve under `project_dir`; dependencies resolve under
            `project_dir / "dbt_packages"`.

    Returns:
        Path | None: The resource path when it exists, otherwise None.
    """
    project_name = project_dir.name

    if resource["package_name"] == project_name:
        path = project_dir / resource["original_file_path"]
    else:
        path = project_dir / "dbt_packages" / resource["original_file_path"]

    if path.exists():
        return path


def bundle_docs(project_dir: Path, output_dir: Path | None = None) -> Path:
    """Bundle `dbt docs generate` output into a single HTML file.

    Embeds `target/manifest.json` and `target/catalog.json` into
    `target/index.html` and writes the result to the destination directory.

    Source: https://data-banana.github.io/dbt-generate-doc-in-one-static-html-file.html

    Args:
        project_dir (Path): The dbt project directory containing `target/`.
        output_dir (Path | None, optional): Destination directory for the
            bundled `index.html`. Defaults to `project_dir / "docs"`.

    Returns:
        Path: The written bundled `index.html` file.
    """
    if output_dir is None:
        output_dir = project_dir / "docs"

    target_dir = project_dir / "target"
    html_file = target_dir / "index.html"
    manifest_file = target_dir / "manifest.json"
    catalog_file = target_dir / "catalog.json"
    output_file = output_dir / "index.html"

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

    os.makedirs(output_file.parent, exist_ok=True)
    with open(output_file, "w") as fp:
        fp.write(html)

    return output_file


def normalize_rows_affected(value: int | str | None) -> int | None:
    """Normalize a dbt adapter `rows_affected` response value.

    Args:
        value (int | str | None): The raw `rows_affected` value, which may be
            an int, a numeric string, or None.

    Returns:
        int | None: The non-negative row count, or None when the value is
            missing, negative, or not a plain digit string.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def to_ns(dt: datetime.datetime) -> int:
    """Convert a datetime to nanoseconds since the epoch.

    Args:
        dt (datetime.datetime): The datetime to convert. Naive datetimes are
            assumed to be UTC.

    Returns:
        int: Nanoseconds since the epoch, for use as span timestamps.

    Raises:
        ValueError: If `dt` is None.
    """
    if dt is None:
        raise ValueError("dt is None")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return int(dt.timestamp() * 1e9)


def list_tables(client: Client, database: str, table_pattern: str = "%") -> list[str]:
    """List table names in a ClickHouse database.

    Args:
        client (Client): The ClickHouse client.
        database (str): The database to query via `system.tables`.
        table_pattern (str, optional): Case-insensitive `ILIKE` pattern.
            Defaults to "%".

    Returns:
        list[str]: Matching table names ordered by name.
    """
    query = """
    select name
    from system.tables
    where
        database = {database:String}
        and name ilike {table_pattern:String}
    order by name
    """
    result = client.query(query, parameters={"database": database, "table_pattern": table_pattern})
    tables = [row[0] for row in result.result_rows]
    return tables


def describe_table(client: Client, database: str, table: str):
    """Describe a ClickHouse table's schema and columns.

    Runs `SHOW CREATE TABLE` (parsed via `parse_create_table_statement`) and
    `DESCRIBE TABLE` against the given table.

    Args:
        client (Client): The ClickHouse client.
        database (str): The database containing the table.
        table (str): The table name.

    Returns:
        dict: The parsed `SHOW CREATE TABLE` statement merged with a
            `columns` key holding `{"name", "data_type"}` entries.
    """
    query = "show create table {database:Identifier}.{table:Identifier}"
    statement = client.query(query, parameters={"database": database, "table": table}).first_row[0]
    parsed = parse_create_table_statement(statement)

    query = "describe table {database:Identifier}.{table:Identifier}"
    result = client.query(query, parameters={"database": database, "table": table})
    columns = [{"name": row[0], "data_type": row[1]} for row in result.result_rows]

    return {**parsed, "columns": columns}


def dump_source_yaml(data: dict, line_length: int | None = None) -> str:
    """Dump a dbt sources YAML document with blank lines between blocks.

    Args:
        data (dict): The `{"version": 2, "sources": [...]}` document.
        line_length (int | None, optional): Maximum line width passed to the
            YAML dumper. Defaults to None.

    Returns:
        str: The formatted YAML document.
    """
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = line_length
    cm = CommentedMap(data)

    # Add blank line between version and sources
    if "sources" in cm:
        cm.yaml_set_comment_before_after_key("sources", before="\n")

    # Add blank line between tables
    for source in cm.get("sources", []):
        tables = source.get("tables")
        if tables:
            seq = CommentedSeq(tables)
            for i in range(1, len(seq)):
                seq.yaml_set_comment_before_after_key(i, before="\n")
            source["tables"] = seq

    stream = StringIO()
    yaml.dump(cm, stream)
    return stream.getvalue()


def dump_model_yaml(data: dict, line_length: int | None = None) -> str:
    """Dump a dbt models YAML document with blank lines between blocks.

    Multiline strings are rendered in literal (`|`) style with trailing
    newlines stripped.

    Args:
        data (dict): The `{"version": 2, "models": [...]}` document.
        line_length (int | None, optional): Maximum line width passed to the
            YAML dumper. Defaults to None.

    Returns:
        str: The formatted YAML document.
    """
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = line_length

    # Custom representer for multiline strings
    def str_representer(dumper, value):
        """Represent strings, using literal style for multiline values."""
        if "\n" in value:
            return dumper.represent_scalar("tag:yaml.org,2002:str", value.rstrip("\n"), style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", value)

    yaml.representer.add_representer(str, str_representer)

    cm = CommentedMap(data)

    # Add blank line between version and models
    if "models" in cm:
        cm.yaml_set_comment_before_after_key("models", before="\n")

    stream = StringIO()
    yaml.dump(cm, stream)
    return stream.getvalue()


class Dbt:
    """Programmatic interface to a dbt project via `dbtRunner`.

    Invocation methods (`build`, `compile`, `parse`, `run`, `run_operation`,
    `seed`, `docs_generate`) return dataclass wrappers holding the
    `dbtRunnerResult` plus optionally captured dbt events. The dbt file logger
    runs in both modes. `build`, `run`, `run_operation`, and `seed` also emit
    OpenTelemetry tracing spans.
    """

    def __init__(
        self,
        profiles_dir: Path | None = None,
        project_dir: Path | None = None,
        target: str | None = None,
    ) -> None:
        """Initialize the dbt project interface.

        Args:
            profiles_dir (Path | None, optional): Directory containing
                `profiles.yml`. Defaults to `find_profiles_dir()`.
            project_dir (Path | None, optional): Project directory containing
                `dbt_project.yml`. Defaults to `find_project_dir()`.
            target (str | None, optional): Default dbt target used when a
                method is called without an explicit `target`. Defaults to None.
        """
        self._profiles_dir = profiles_dir or find_profiles_dir()
        self._project_dir = project_dir or find_project_dir()
        self._target = target

    @cached_property
    def profiles_file(self) -> Path:
        """Return the `profiles.yml` file path.

        Returns:
            Path: `profiles_dir / "profiles.yml"`.
        """
        return self._profiles_dir / "profiles.yml"

    @cached_property
    def project_dir(self) -> Path:
        """Return the dbt project directory.

        Returns:
            Path: The configured project directory.
        """
        return self._project_dir

    @cached_property
    def project_config_file(self) -> Path:
        """Return the `dbt_project.yml` file path.

        Returns:
            Path: `project_dir / "dbt_project.yml"`.
        """
        return self._project_dir / "dbt_project.yml"

    @cached_property
    def project_config(self):
        """Load the parsed `dbt_project.yml` configuration.

        Returns:
            dict: The project configuration (e.g. `macro-paths`,
                `model-paths`).
        """
        yaml = YAML(typ="safe", pure=True)
        return yaml.load(self.project_config_file)

    @cached_property
    def docs_dir(self) -> Path:
        """Return the generated docs directory.

        Returns:
            Path: `project_dir / "docs"`.
        """
        return self._project_dir / "docs"

    @cached_property
    def models_dir(self) -> Path:
        """Return the models directory.

        Returns:
            Path: `project_dir / "models"`.
        """
        return self._project_dir / "models"

    def get_resource(self, name: str, invalidate_cache: bool = False) -> DbtModel | DbtSeed | None:
        """Get a single manifest resource by name.

        Args:
            name (str): The resource name to select.
            invalidate_cache (bool, optional): Re-parse the manifest before
                listing. Defaults to False.

        Returns:
            DbtModel | DbtSeed | None: The first matching resource, or None
                when no resource matches.
        """
        resources = self.list_resources(select=name, invalidate_cache=invalidate_cache)

        if not resources:
            return None

        return resources[0]

    def list_resources(
        self,
        resource_types: list[DbtResourceType] | None = None,
        select: str | None = None,
        invalidate_cache: bool = False,
    ) -> list[DbtModel | DbtSeed]:
        """List manifest resources, parsing the manifest on a cold cache.

        Args:
            resource_types (list[DbtResourceType] | None, optional): Resource
                types to include. Defaults to all supported types (model, seed).
            select (str | None, optional): Return only the resource with this
                name. Defaults to None (return all).
            invalidate_cache (bool, optional): Re-parse the manifest before
                listing. Defaults to False.

        Returns:
            list[DbtModel | DbtSeed]: Matching resources sorted by name.

        Raises:
            ValueError: If an unsupported `resource_types` entry is given.
            DbtManifestNotFoundException: If no `manifest.json` exists after parsing.
        """
        valid_resource_types = sorted(RESOURCE_TYPE_TO_CLASS.keys())

        if resource_types is None:
            resource_types = valid_resource_types

        for resource_type in resource_types:
            if resource_type not in valid_resource_types:
                raise ValueError(
                    f"'resource_types' must be any of: {', '.join(valid_resource_types)}"
                )

        manifest_file = self.project_dir / "target" / "manifest.json"

        if not os.path.exists(manifest_file) or invalidate_cache:
            self.parse(quiet=True)

            if not os.path.exists(manifest_file):
                raise DbtManifestNotFoundException(
                    f"'{manifest_file}' not found. Run 'dbt parse' or 'dbt compile' first."
                )

        with open(manifest_file) as f:
            data = json.load(f)

        resources: dict[str, DbtModel | DbtSeed] = {}
        for resource_dict in data.get("nodes", {}).values():
            resource_type = resource_dict.get("resource_type")

            if (resource_types and resource_type not in resource_types) or (
                resource_type not in RESOURCE_TYPE_TO_CLASS
            ):
                continue

            class_: DbtModel | DbtSeed = RESOURCE_TYPE_TO_CLASS[resource_type]
            resource = class_(**resource_dict)
            resources[resource.name] = resource

        selected_resources: list[DbtModel | DbtSeed] = []
        if select:
            resource = resources.get(select)
            if resource:
                selected_resources = [resource]
        else:
            selected_resources = list(resources.values())

        return pydash.sort_by(selected_resources, lambda resource: resource.name)

    def build(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        full_refresh: bool | None = False,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
        capture_events: bool = False,
    ) -> DbtInvocationResult:
        """Run `dbt build` (seeds, models, snapshots, and tests in DAG order).

        Emits OpenTelemetry tracing spans for the invocation and each node.

        Args:
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            full_refresh (bool | None, optional): Pass `--full-refresh`.
                Defaults to False.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtInvocationResult: The runner result plus captured events.
        """
        cmd = self._build_command(
            debug=debug,
            fail_fast=fail_fast,
            full_refresh=full_refresh,
            exclude=exclude,
            quiet=quiet,
            select=select,
            selector=selector,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )
        runner_result, events = _invoke(cmd, capture_events)

        raw_command = shlex.join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(
            DbtCommand.BUILD,
            raw_command,
            invocation_id,
            runner_result,
            full_refresh=full_refresh,
        )

        return DbtInvocationResult(runner_result=runner_result, events=events)

    def compile(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        capture_events: bool = False,
    ) -> DbtInvocationResult:
        """Run `dbt compile` (generate executable SQL into `target/`).

        Args:
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtInvocationResult: The runner result plus captured events.
        """
        cmd = self._compile_command(
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            select=select,
            target=target,
            use_colors=use_colors,
        )
        runner_result, events = _invoke(cmd, capture_events)

        return DbtInvocationResult(runner_result=runner_result, events=events)

    def parse(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        target: str | None = None,
        use_colors: bool | None = False,
        capture_events: bool = False,
    ) -> DbtInvocationResult:
        """Run `dbt parse` (parse the project and return the manifest).

        Args:
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to False.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtInvocationResult: The runner result plus captured events.
        """
        cmd = self._parse_command(
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            target=target,
            use_colors=use_colors,
        )
        runner_result, events = _invoke(cmd, capture_events)

        return DbtInvocationResult(runner_result=runner_result, events=events)

    def run(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        full_refresh: bool | None = False,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
        capture_events: bool = False,
    ) -> DbtInvocationResult:
        """Run `dbt run` (compile SQL and execute against the target database).

        Emits OpenTelemetry tracing spans for the invocation and each node.

        Args:
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            full_refresh (bool | None, optional): Pass `--full-refresh`.
                Defaults to False.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtInvocationResult: The runner result plus captured events.
        """
        cmd = self._run_command(
            debug=debug,
            fail_fast=fail_fast,
            full_refresh=full_refresh,
            exclude=exclude,
            quiet=quiet,
            select=select,
            selector=selector,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )
        runner_result, events = _invoke(cmd, capture_events)

        raw_command = shlex.join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(
            DbtCommand.RUN,
            raw_command,
            invocation_id,
            runner_result,
            full_refresh=full_refresh,
        )

        return DbtInvocationResult(runner_result=runner_result, events=events)

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
        capture_events: bool = False,
    ) -> DbtInvocationResult:
        """Run the named macro with `dbt run-operation`.

        Emits OpenTelemetry tracing spans for the invocation and its nodes.

        Args:
            macro (str): The macro to run.
            args (dict[str, Any] | None, optional): Value for `--args`,
                serialized as JSON. Defaults to None.
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to False.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtInvocationResult: The runner result plus captured events.
        """
        cmd = self._run_operation_command(
            macro,
            args=args,
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )
        runner_result, events = _invoke(cmd, capture_events)

        raw_command = shlex.join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(DbtCommand.RUN_OPERATION, raw_command, invocation_id, runner_result)

        return DbtInvocationResult(runner_result=runner_result, events=events)

    def seed(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        capture_events: bool = False,
    ) -> DbtInvocationResult:
        """Run `dbt seed` (load CSV files into the warehouse).

        Emits OpenTelemetry tracing spans for the invocation and each node.

        Args:
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtInvocationResult: The runner result plus captured events.
        """
        cmd = self._seed_command(
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            select=select,
            target=target,
            use_colors=use_colors,
        )
        runner_result, events = _invoke(cmd, capture_events)

        raw_command = shlex.join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(DbtCommand.SEED, raw_command, invocation_id, runner_result)

        return DbtInvocationResult(runner_result=runner_result, events=events)

    def generate_source_yaml(
        self,
        adapter: ClickHouseAdapter,
        database: str | None = None,
        table_pattern: str = "%",
        source_props: dict[str, Any] | None = None,
        table_config_meta_props: list[str] | None = None,
        line_length: int | None = None,
    ) -> str:
        """Generate the source schema YAML for ClickHouse tables.

        Introspects each matching table and emits a `{version: 2, sources: ...}`
        document via `dump_source_yaml`.

        Args:
            adapter (ClickHouseAdapter): Adapter used to query table metadata.
            database (str | None, optional): Database to introspect. Defaults
                to the adapter's configured database.
            table_pattern (str, optional): Case-insensitive `ILIKE` pattern.
                Defaults to "%".
            source_props (dict[str, Any] | None, optional): Extra properties
                merged into the generated source entry. Defaults to None.
            table_config_meta_props (list[str] | None, optional): Table
                metadata keys picked into each table's `config.meta`.
                Defaults to None (no `config` block).
            line_length (int | None, optional): Maximum YAML line width.
                Defaults to None.

        Returns:
            str: The formatted sources YAML document.
        """
        if database is None:
            database = adapter.settings.database

        data = {"version": 2, "sources": []}
        with adapter.create_client() as client:
            table_names = list_tables(client, database, table_pattern)
            tables = []
            for table_name in table_names:
                metadata = describe_table(client, database, table_name)
                config = (
                    {"config": {"meta": pydash.pick(metadata, *table_config_meta_props)}}
                    if table_config_meta_props
                    else {}
                )
                tables.append({"name": table_name, **config, "columns": metadata["columns"]})
            data["sources"].append({"name": database, **(source_props or {}), "tables": tables})

        return dump_source_yaml(data, line_length=line_length)

    def generate_model_yaml(
        self,
        adapter: ClickHouseAdapter,
        database: str | None = None,
        table_pattern: str = "%",
        merge: bool = False,
        line_length: int | None = None,
    ) -> dict[str, str]:
        """Generate per-model schema YAML documents for ClickHouse tables.

        With `merge=True`, existing model/column descriptions and `meta`
        from the manifest are preserved, and columns are narrowed to
        `name`, `description`, `meta`, and `data_type`.

        Args:
            adapter (ClickHouseAdapter): Adapter used to query table metadata.
            database (str | None, optional): Database to introspect. Defaults
                to the adapter's configured database.
            table_pattern (str, optional): Case-insensitive `ILIKE` pattern.
                Defaults to "%".
            merge (bool, optional): Merge descriptions and `meta` from the
                parsed manifest models. Defaults to False.
            line_length (int | None, optional): Maximum YAML line width.
                Defaults to None.

        Returns:
            dict[str, str]: Mapping of table name to formatted models YAML.
        """
        if database is None:
            database = adapter.settings.database

        result = {}
        with adapter.create_client() as client:
            table_names = list_tables(client, database, table_pattern)
            for table_name in table_names:
                metadata = describe_table(client, database, table_name)
                result[table_name] = {
                    "version": 2,
                    "models": [{"name": table_name, "columns": metadata["columns"]}],
                }

        if result:
            if merge:
                resources = self.list_resources(
                    resource_types=[DbtResourceType.MODEL], invalidate_cache=True
                )

                for table_name, data in result.items():
                    resource: DbtModel = pydash.find(
                        resources,
                        lambda resource: resource.name == table_name,  # noqa: B023
                    )

                    if not resource:
                        continue

                    model = data["models"][0]

                    if len(resource.description.strip()):
                        model["description"] = resource.description.strip()

                    columns = []

                    for column in model["columns"]:
                        resource_column = pydash.find(
                            resource.columns,
                            lambda resource_column: resource_column.name == column["name"],  # noqa: B023
                        )

                        if resource_column:
                            if len(resource_column.description.strip()):
                                column["description"] = resource_column.description.strip()

                            if resource_column.meta:
                                column["meta"] = resource_column.meta

                        columns.append(
                            pydash.pick(column, ["name", "description", "meta", "data_type"])
                        )

                    model["columns"] = columns
                    data["models"][0] = pydash.pick(model, ["name", "description", "columns"])
            else:
                pass

        return {
            table_name: dump_model_yaml(data, line_length=line_length)
            for table_name, data in result.items()
        }

    def docs_generate(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        quiet: bool | None = True,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
        capture_events: bool = False,
    ) -> DbtDocsGenerateResult:
        """Run `dbt docs generate` and bundle the site into a single HTML file.

        Args:
            debug (bool | None, optional): Pass `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Pass `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Pass `--quiet` instead of
                `--no-quiet`. Defaults to True.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Pass `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.
            capture_events (bool, optional): Collect dbt events (EventMsg) via
                runner callbacks. The dbt file logger runs in both modes.
                Defaults to False.

        Returns:
            DbtDocsGenerateResult: The runner result, the bundled
                `output_file`, and captured events.
        """
        cmd = self._docs_generate_command(
            debug=debug,
            fail_fast=fail_fast,
            exclude=exclude,
            quiet=quiet,
            select=select,
            selector=selector,
            target=target,
            use_colors=use_colors,
            vars=vars,
        )
        runner_result, events = _invoke(cmd, capture_events)
        output_file = bundle_docs(self._project_dir)

        return DbtDocsGenerateResult(
            runner_result=runner_result, output_file=output_file, events=events
        )

    def docs_serve(self):
        """Serve the generated docs site with live reload.

        Generates the docs first when `docs/index.html` does not exist, then
        watches `macro-paths` (`*.sql`) and `model-paths` (`*.sql`, `*.yml`)
        for changes — regenerating on each change — while serving `docs_dir`
        on `0.0.0.0:8080`.

        Returns:
            None: This method blocks while serving.
        """
        # If the docs page has not been generated before, then do so now
        if not os.path.exists(os.path.join(self.docs_dir, "index.html")):
            self.docs_generate()

        watch_paths = [self.project_config_file]
        for path in self.project_config["macro-paths"]:
            watch_paths.extend(
                [
                    os.path.join(self._project_dir, path, "**", "*.sql"),
                ]
            )
        for path in self.project_config["model-paths"]:
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
        server.serve(host="0.0.0.0", port=8080, root=self.docs_dir)

    def _build_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        full_refresh: bool | None = False,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the `dbt build` command argv.

        Args:
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            full_refresh (bool | None, optional): Append `--full-refresh` when
                True. Defaults to False.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "build",
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
            cmd.extend(["--vars", json.dumps(vars)])

        return cmd

    def _compile_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the `dbt compile` command argv.

        Args:
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "compile",
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
            cmd.extend(["--vars", json.dumps(vars)])

        return cmd

    def _parse_command(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the `dbt parse` command argv.

        Args:
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
        if target is None:
            target = self._target

        cmd = [
            "dbt",
            "parse",
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

        if target:
            cmd.extend(["--target", target])

        if use_colors:
            cmd.extend(["--use-colors"])
        else:
            cmd.extend(["--no-use-colors"])

        if vars:
            cmd.extend(["--vars", json.dumps(vars)])

        return cmd

    def _run_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        full_refresh: bool | None = False,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the `dbt run` command argv.

        Args:
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            full_refresh (bool | None, optional): Append `--full-refresh` when
                True. Defaults to False.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
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
            cmd.extend(["--vars", json.dumps(vars)])

        return cmd

    def _run_operation_command(
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
        """Build the `dbt run-operation` command argv.

        Args:
            macro (str): The macro to run, passed positionally.
            args (dict[str, Any] | None, optional): Value for `--args`,
                serialized as JSON. Defaults to None.
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
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
            cmd.extend(["--vars", json.dumps(vars)])

        return cmd

    def _seed_command(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
    ) -> list[str]:
        """Build the `dbt seed` command argv.

        Note: unlike the other builders, this command accepts no `vars`.

        Args:
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
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

    def _docs_generate_command(
        self,
        debug: bool | None = False,
        exclude: str | None = None,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        selector: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
        vars: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the `dbt docs generate` command argv.

        Args:
            debug (bool | None, optional): Emit `--debug` instead of
                `--no-debug`. Defaults to False.
            exclude (str | None, optional): Value for `--exclude`. Defaults
                to None.
            fail_fast (bool | None, optional): Emit `--fail-fast` instead of
                `--no-fail-fast`. Defaults to True.
            quiet (bool | None, optional): Emit `--quiet` instead of
                `--no-quiet`. Defaults to False.
            select (str | None, optional): Value for `--select`. Defaults
                to None.
            selector (str | None, optional): Value for `--selector`. Defaults
                to None.
            target (str | None, optional): Value for `--target`. Falls back to
                the instance target. Defaults to None.
            use_colors (bool | None, optional): Emit `--use-colors` instead of
                `--no-use-colors`. Defaults to False.
            vars (dict[str, Any] | None, optional): Value for `--vars`,
                serialized as JSON. Defaults to None.

        Returns:
            list[str]: Command argv starting with `"dbt"`.
        """
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
            cmd.extend(["--vars", json.dumps(vars)])

        return cmd


def _trace_invocation(
    command: DbtCommand,
    raw_command: str,
    invocation_id: str,
    runner_result: dbtRunnerResult,
    full_refresh: bool | None = False,
) -> None:
    """Emit OpenTelemetry spans for a dbt invocation and its nodes.

    Creates a root `dbt.invoke` span with per-node `dbt.node.invoke` child
    spans (plus nested `dbt.node.compile` / `dbt.node.execute` spans when
    timing is available). `Success` maps to OK, `Error` to ERROR with the
    failure recorded, `Skipped` to UNSET; any other status raises. Timestamps
    come from node timings, falling back to the result `generated_at`.

    Args:
        command (DbtCommand): The invoked dbt command.
        raw_command (str): The shell-joined command argv for attributes.
        invocation_id (str): Unique ID naming the root span.
        runner_result (dbtRunnerResult): The invocation result to trace.
        full_refresh (bool | None, optional): Recorded as
            `dbt.invoke.full_refresh`. Defaults to False.

    Returns:
        None.

    Raises:
        UnsupportedCommandException: If `command` has no trace mapping.
        UnsupportedRunStatusException: If a node status is not
            Success, Error, or Skipped.
    """
    tracer = trace.get_tracer(__name__)

    def truncate_str(value: str | None, max_length: int = 200) -> str | None:
        """Truncate a string with a `"... (truncated)"` suffix.

        Args:
            value (str | None): The value to truncate.
            max_length (int, optional): Maximum length before truncation.
                Defaults to 200.

        Returns:
            str | None: The original value when short enough, otherwise the
                truncated value.
        """
        if value is None:
            return None
        if len(value) <= max_length:
            return value
        return value[:max_length] + "... (truncated)"

    class ParsedRoot(BaseModel):
        """Validated invocation-level trace attributes."""

        raw_command: str
        invocation_id: str
        full_refresh: bool
        generated_at: datetime.datetime

    # Based on https://github.com/elementary-data/dbt-data-reliability/blob/6551383e8a37e5814bd2bb9fd74330be8265a3c9/models/run_results.yml#L133
    class ParsedNode(BaseModel):
        """Validated per-node trace attributes."""

        unique_id: str
        name: str
        message: str | None = None
        status: RunStatus
        resource_type: str
        execution_time: float
        compile_started_at: datetime.datetime | None = None
        compile_completed_at: datetime.datetime | None = None
        execute_started_at: datetime.datetime | None = None
        execute_completed_at: datetime.datetime | None = None
        rows_affected: int | None = 0
        compiled_code: str | None = None
        failures: int | None = 0
        query_id: str | None = None
        thread_id: str | None = None
        materialization: str | None = None
        adapter_response: str | None = None

    parsed_nodes: list[ParsedNode] = []

    if command in {DbtCommand.BUILD, DbtCommand.RUN, DbtCommand.SEED}:
        generated_at = runner_result.result.generated_at

        for node_result in runner_result.result.results:
            compile_started_at = None
            compile_completed_at = None
            execute_started_at = None
            execute_completed_at = None

            for timing_info in node_result.timing:
                if timing_info.name == "compile":
                    compile_started_at = timing_info.started_at
                    compile_completed_at = timing_info.completed_at
                elif timing_info.name == "execute":
                    execute_started_at = timing_info.started_at
                    execute_completed_at = timing_info.completed_at

            if isinstance(node_result.node, ModelNode):
                compiled_code = node_result.node.compiled_code
            else:
                compiled_code = None

            parsed_node = ParsedNode(
                unique_id=node_result.node.unique_id,
                name=node_result.node.name,
                message=node_result.message,
                status=node_result.status,
                resource_type=node_result.node.resource_type,
                execution_time=node_result.execution_time,
                compile_started_at=compile_started_at,
                compile_completed_at=compile_completed_at,
                execute_started_at=execute_started_at,
                execute_completed_at=execute_completed_at,
                rows_affected=normalize_rows_affected(
                    node_result.adapter_response.get("rows_affected")
                ),
                compiled_code=compiled_code,
                failures=node_result.failures,
                query_id=node_result.adapter_response.get("query_id"),
                thread_id=node_result.thread_id,
                materialization=node_result.node.config.materialized,
                adapter_response=json.dumps(node_result.adapter_response),
            )
            parsed_nodes.append(parsed_node)

    elif command == DbtCommand.RUN_OPERATION:
        generated_at = runner_result.result.metadata.generated_at

        for node_result in runner_result.result.results:
            compile_started_at = None
            compile_completed_at = None
            execute_started_at = None
            execute_completed_at = None

            for timing_info in node_result.timing:
                if timing_info.name == "compile":
                    compile_started_at = timing_info.started_at
                    compile_completed_at = timing_info.completed_at
                elif timing_info.name == "execute":
                    execute_started_at = timing_info.started_at
                    execute_completed_at = timing_info.completed_at

            parsed_node = ParsedNode(
                unique_id=node_result.unique_id,
                name=runner_result.result.args["macro"],
                message=node_result.message,
                status=node_result.status,
                resource_type="operation",
                execution_time=node_result.execution_time,
                compile_started_at=compile_started_at,
                compile_completed_at=compile_completed_at,
                execute_started_at=execute_started_at,
                execute_completed_at=execute_completed_at,
                rows_affected=normalize_rows_affected(
                    node_result.adapter_response.get("rows_affected")
                ),
                compiled_code=None,
                failures=node_result.failures,
                query_id=node_result.adapter_response.get("query_id"),
                thread_id=node_result.thread_id,
                materialization=None,
                adapter_response=json.dumps(node_result.adapter_response),
            )
            parsed_nodes.append(parsed_node)

    else:
        raise UnsupportedCommandException(f"Command '{command}' is not supported")

    parsed_root = ParsedRoot(
        raw_command=raw_command,
        invocation_id=invocation_id,
        full_refresh=full_refresh,
        generated_at=generated_at,
    )

    if not parsed_nodes:
        return

    root_dts = (
        [node.compile_started_at for node in parsed_nodes]
        + [node.compile_completed_at for node in parsed_nodes]
        + [node.execute_started_at for node in parsed_nodes]
        + [node.execute_completed_at for node in parsed_nodes]
    )
    root_dts = [dt for dt in root_dts if dt]
    root_start_dt = min(root_dts) if root_dts else parsed_root.generated_at
    root_end_dt = max(root_dts) if root_dts else parsed_root.generated_at

    root_attrs = {
        "dbt.invoke.command": command,
        "dbt.invoke.raw_command": raw_command,
        "dbt.invoke.full_refresh": full_refresh,
        "dbt.invoke.invocation_id": invocation_id,
        "dbt.invoke.node_count": len(parsed_nodes),
        "dbt.invoke.generated_at": parsed_root.generated_at.isoformat(),
    }

    # create root span but don't end it automatically; we want to set custom end_time
    with tracer.start_as_current_span(
        f"dbt.invoke {invocation_id}",
        attributes=root_attrs,
        start_time=to_ns(root_start_dt),
        end_on_exit=False,
    ) as root_span:
        # iterate nodes and create child spans
        for n in parsed_nodes:
            node_dts = [
                n.compile_started_at,
                n.compile_completed_at,
                n.execute_started_at,
                n.execute_completed_at,
            ]
            node_dts = [dt for dt in node_dts if dt]
            node_start_dt = min(node_dts) if node_dts else parsed_root.generated_at
            node_end_dt = max(node_dts) if node_dts else parsed_root.generated_at

            node_attrs = {
                "dbt.node.unique_id": n.unique_id,
                "dbt.node.name": n.name,
                "dbt.node.resource_type": n.resource_type,
                "dbt.node.materialization": n.materialization or "",
                "dbt.node.rows_affected": int(n.rows_affected or 0),
                "dbt.node.query_id": n.query_id or "",
                "dbt.node.thread_id": n.thread_id or "",
            }

            # keep largest text fields trimmed
            if n.adapter_response:
                node_attrs["dbt.node.adapter_response_excerpt"] = truncate_str(
                    n.adapter_response, 200
                )

            # start node span with explicit timestamp and don't end on exit so we can set end_time
            with tracer.start_as_current_span(
                f"dbt.node.invoke {n.name}",
                attributes=node_attrs,
                start_time=to_ns(node_start_dt),
                end_on_exit=False,
            ) as node_span:
                # record compile nested span if we have timestamps
                if n.compile_started_at and n.compile_completed_at:
                    with tracer.start_as_current_span(
                        "dbt.node.compile",
                        start_time=to_ns(n.compile_started_at),
                        end_on_exit=False,
                    ) as compile_span:
                        compile_span.end(end_time=to_ns(n.compile_completed_at))

                # record execute nested span if we have timestamps
                if n.execute_started_at and n.execute_completed_at:
                    with tracer.start_as_current_span(
                        "dbt.node.execute",
                        start_time=to_ns(n.execute_started_at),
                        end_on_exit=False,
                    ) as execute_span:
                        execute_span.end(end_time=to_ns(n.execute_completed_at))

                if n.status == RunStatus.Success:
                    node_span.set_status(trace.Status(trace.StatusCode.OK))
                elif n.status == RunStatus.Error:
                    message = n.message or f"status={n.status}"
                    node_span.record_exception(Exception(message))
                    node_span.set_status(trace.Status(trace.StatusCode.ERROR, message))
                    node_span.add_event("dbt.node.failure", {"failures": int(n.failures or 0)})
                elif n.status == RunStatus.Skipped:
                    node_span.set_status(trace.Status(trace.StatusCode.UNSET))
                else:
                    raise UnsupportedRunStatusException(f"Run status '{n.status}' is not supported")

                # attach the textual message as an event
                if n.message:
                    node_span.add_event("dbt.node.message", {"message": n.message})

                # end node span with explicit end_time
                node_span.end(end_time=to_ns(node_end_dt))

        # now end root span with run end timestamp
        root_span.end(end_time=to_ns(root_end_dt))
