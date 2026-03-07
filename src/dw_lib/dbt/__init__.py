from ..utils.filesystem import find_up
from .types import DbtCommand, DbtModel, DbtResourceType, DbtSeed
from clickhouse_connect.driver.client import Client
from datetime import datetime, timezone
from dbt.artifacts.schemas.results import RunStatus
from dbt.cli.main import dbtRunner, dbtRunnerResult
from dbt.contracts.graph.nodes import ModelNode
from dw_lib.database import ClickHouseAdapter
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

import json
import os
import pydash
import yaml

RESOURCE_TYPE_TO_CLASS = {
    DbtResourceType.MODEL: DbtModel,
    DbtResourceType.SEED: DbtSeed,
}


def find_profiles_dir() -> Path:
    dbt_profiles_dir = os.environ.get("DBT_PROFILES_DIR")

    if dbt_profiles_dir:
        return Path(dbt_profiles_dir)

    return Path.home() / ".dbt"


def find_project_config_file() -> Path:
    dbt_project_dir = os.environ.get("DBT_PROJECT_DIR")

    if dbt_project_dir:
        cwd = Path(dbt_project_dir)
    else:
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


def normalize_rows_affected(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def to_ns(dt: datetime) -> int:
    """Convert a timezone-aware (or naive assumed UTC) datetime to nanoseconds since epoch."""
    if dt is None:
        raise ValueError("dt is None")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1e9)


def list_tables(client: Client, database: str, table_pattern: str = "%") -> list[str]:
    query = """
    SELECT name
    FROM system.tables
    WHERE database = {database:String}
    AND name ILIKE {table_pattern:String}
    ORDER BY name
    """
    result = client.query(query, parameters={"database": database, "table_pattern": table_pattern})
    tables = [row[0] for row in result.result_rows]
    return tables


def describe_table(client: Client, database: str, table: str):
    query = """
    DESCRIBE TABLE {database:Identifier}.{table:Identifier}
    """
    result = client.query(query, parameters={"database": database, "table": table})
    columns = [{"name": row[0], "data_type": row[1]} for row in result.result_rows]
    return columns


def dump_source_yaml(data: dict) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
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


def dump_model_yaml(data: dict) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    cm = CommentedMap(data)

    # Add blank line between version and models
    if "models" in cm:
        cm.yaml_set_comment_before_after_key("models", before="\n")

    stream = StringIO()
    yaml.dump(cm, stream)
    return stream.getvalue()


class Dbt:
    def __init__(
        self,
        profiles_dir: Path | None = None,
        project_dir: Path | None = None,
        target: str | None = None,
    ) -> None:
        self._profiles_dir = profiles_dir or find_profiles_dir()
        self._project_dir = project_dir or find_project_dir()
        self._target = target

    @cached_property
    def profiles_file(self) -> Path:
        return self._profiles_dir / "profiles.yml"

    @cached_property
    def project_dir(self) -> Path:
        return self._project_dir

    @cached_property
    def project_config_file(self) -> Path:
        return self._project_dir / "dbt_project.yml"

    @cached_property
    def project_config(self):
        with open(self.project_config_file) as fp:
            data = yaml.safe_load(fp)
        return data

    @cached_property
    def docs_dir(self) -> Path:
        return self._project_dir / "docs"

    @cached_property
    def models_dir(self) -> Path:
        return self._project_dir / "models"

    def get_resource(self, name: str) -> DbtModel | DbtSeed | None:
        resources = self.list_resources(select=name)

        if not resources:
            return None

        return resources[0]

    def list_resources(
        self,
        resource_types: list[DbtResourceType] | None = None,
        select: str | None = None,
    ) -> list[DbtModel | DbtSeed]:
        valid_resource_types = RESOURCE_TYPE_TO_CLASS.keys()

        if resource_types is None:
            resource_types = valid_resource_types

        for resource_type in resource_types:
            if resource_type not in valid_resource_types:
                raise ValueError(
                    f"'resource_types' must be any of: {', '.join(valid_resource_types)}"
                )

        manifest_file = self.project_dir / "target" / "manifest.json"

        if not os.path.exists(manifest_file):
            self.compile(quiet=True)

            if not os.path.exists(manifest_file):
                raise Exception(f"'{manifest_file}' not found. Run 'dbt compile' first.")

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

    def compile(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
    ) -> dbtRunnerResult:
        cmd = self._compile_command(
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            select=select,
            target=target,
            use_colors=use_colors,
        )
        runner_result = dbtRunner().invoke(cmd[1:])

        return runner_result

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
        cmd = self._run_command(
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
        runner_result = dbtRunner().invoke(cmd[1:])

        raw_command = " ".join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(
            DbtCommand.RUN,
            raw_command,
            invocation_id,
            runner_result,
            full_refresh=full_refresh,
        )

        return runner_result

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
        runner_result = dbtRunner().invoke(cmd[1:])

        raw_command = " ".join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(DbtCommand.RUN_OPERATION, raw_command, invocation_id, runner_result)

        return runner_result

    def seed(
        self,
        debug: bool | None = False,
        fail_fast: bool | None = True,
        quiet: bool | None = False,
        select: str | None = None,
        target: str | None = None,
        use_colors: bool | None = False,
    ) -> dbtRunnerResult:
        cmd = self._seed_command(
            debug=debug,
            fail_fast=fail_fast,
            quiet=quiet,
            select=select,
            target=target,
            use_colors=use_colors,
        )
        runner_result = dbtRunner().invoke(cmd[1:])

        raw_command = " ".join(cmd)
        invocation_id = str(uuid4())
        _trace_invocation(DbtCommand.SEED, raw_command, invocation_id, runner_result)

        return runner_result

    def generate_source_yaml(
        self,
        adapter: ClickHouseAdapter,
        database: str | None = None,
        table_pattern: str = "%",
        source_props=None,
    ) -> str:
        """Generate the schema YAML for the given source."""
        if database is None:
            database = adapter.settings.database

        data = {"version": 2, "sources": []}
        with adapter.create_client() as client:
            table_names = list_tables(client, database, table_pattern)
            tables = []
            for table_name in table_names:
                columns = describe_table(client, database, table_name)
                tables.append({"name": table_name, "columns": columns})
            data["sources"].append({"name": database, **(source_props or {}), "tables": tables})

        return dump_source_yaml(data)

    def generate_model_yaml(
        self,
        adapter: ClickHouseAdapter,
        database: str | None = None,
        table_pattern: str = "%",
    ) -> dict[str, str]:
        """Generate the schema YAML for the given models."""
        if database is None:
            database = adapter.settings.database

        result = {}
        with adapter.create_client() as client:
            table_names = list_tables(client, database, table_pattern)
            for table_name in table_names:
                columns = describe_table(client, database, table_name)
                data = {"version": 2, "models": [{"name": table_name, "columns": columns}]}
                result[table_name] = dump_model_yaml(data)

        return result

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
        cmd = self._docs_generate_command(
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

    def _compile_command(
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

    def _run_command(
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

    def _seed_command(
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

    def _docs_generate_command(
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


def _trace_invocation(
    command: DbtCommand,
    raw_command: str,
    invocation_id: str,
    runner_result: dbtRunnerResult,
    full_refresh: bool | None = False,
) -> None:
    tracer = trace.get_tracer(__name__)

    def truncate_str(value: str | None, max_length: int = 200) -> str | None:
        if value is None:
            return None
        if len(value) <= max_length:
            return value
        return value[:max_length] + "... (truncated)"

    class ParsedRoot(BaseModel):
        raw_command: str
        invocation_id: str
        full_refresh: bool
        generated_at: datetime

    # Based on https://github.com/elementary-data/dbt-data-reliability/blob/6551383e8a37e5814bd2bb9fd74330be8265a3c9/models/run_results.yml#L133
    class ParsedNode(BaseModel):
        unique_id: str
        name: str
        message: str | None = None
        status: RunStatus
        resource_type: str
        execution_time: float
        compile_started_at: datetime | None = None
        compile_completed_at: datetime | None = None
        execute_started_at: datetime | None = None
        execute_completed_at: datetime | None = None
        rows_affected: int | None = 0
        compiled_code: str | None = None
        failures: int | None = 0
        query_id: str | None = None
        thread_id: str | None = None
        materialization: str | None = None
        adapter_response: str | None = None

    parsed_nodes: list[ParsedNode] = []

    if command in {DbtCommand.RUN, DbtCommand.SEED}:
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
        raise Exception(f"Command '{command}' is not supported")

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
                    raise Exception(f"Run status '{n.status}' is not supported")

                # attach the textual message as an event
                if n.message:
                    node_span.add_event("dbt.node.message", {"message": n.message})

                # end node span with explicit end_time
                node_span.end(end_time=to_ns(node_end_dt))

        # now end root span with run end timestamp
        root_span.end(end_time=to_ns(root_end_dt))
