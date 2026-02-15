from ..utils.filesystem import find_up, get_file_extension
from ..utils.yaml_utils import safe_load_file
from .types import DbtCommand, DbtModel, DbtResourceType, DbtSeed, DbtSource
from datetime import datetime, timezone
from dbt.artifacts.schemas.results import RunStatus
from dbt.cli.main import dbtRunner, dbtRunnerResult
from dbt.contracts.graph.nodes import ModelNode
from livereload import Server
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import get_tracer, set_tracer_provider, Status, StatusCode, Tracer
from pathlib import Path
from pydantic import BaseModel
from typing import Any
from uuid import uuid4

import json
import os
import pydash
import subprocess
import yaml

RE_REF = r"^ref\(['\"](.*?)['\"]\)$"
RE_SOURCE = r"^source\(['\"](.*?)['\"], ['\"](.*?)['\"]\)$"

RESOURCE_TYPE_TO_CLASS = {
    DbtResourceType.MODEL: DbtModel,
    DbtResourceType.SEED: DbtSeed,
    DbtResourceType.SOURCE: DbtSource,
}

"""
Map from dbt-codegen to ClickHouse data types that are case-sensitive.
See https://clickhouse.com/docs/en/operations/system-tables/data_type_families
Query:
    select '"' || lower(name) || '": "' || name || '",'
    from system.data_type_families
    where not case_insensitive
    order by name;
"""
CODEGEN_TO_CLICKHOUSE_DATA_TYPE = {
    "aggregatefunction": "AggregateFunction",
    "array": "Array",
    "enum16": "Enum16",
    "enum8": "Enum8",
    "fixedstring": "FixedString",
    "float32": "Float32",
    "float64": "Float64",
    "ipv4": "IPv4",
    "ipv6": "IPv6",
    "int128": "Int128",
    "int16": "Int16",
    "int256": "Int256",
    "int32": "Int32",
    "int64": "Int64",
    "int8": "Int8",
    "intervalday": "IntervalDay",
    "intervalhour": "IntervalHour",
    "intervalmicrosecond": "IntervalMicrosecond",
    "intervalmillisecond": "IntervalMillisecond",
    "intervalminute": "IntervalMinute",
    "intervalmonth": "IntervalMonth",
    "intervalnanosecond": "IntervalNanosecond",
    "intervalquarter": "IntervalQuarter",
    "intervalsecond": "IntervalSecond",
    "intervalweek": "IntervalWeek",
    "intervalyear": "IntervalYear",
    "lowcardinality": "LowCardinality",
    "map": "Map",
    "multipolygon": "MultiPolygon",
    "nested": "Nested",
    "nothing": "Nothing",
    "nullable": "Nullable",
    "object": "Object",
    "point": "Point",
    "polygon": "Polygon",
    "ring": "Ring",
    "simpleaggregatefunction": "SimpleAggregateFunction",
    "string": "String",
    "tuple": "Tuple",
    "uint128": "UInt128",
    "uint16": "UInt16",
    "uint256": "UInt256",
    "uint32": "UInt32",
    "uint64": "UInt64",
    "uint8": "UInt8",
    "uuid": "UUID",
    "variant": "Variant",
}


def get_profiles_dir() -> Path:
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


class Dbt:
    def __init__(
        self,
        project_dir: Path,
        target: str | None = None,
        otlp_service_name: str = "dbt",
        otlp_traces_endpoints: list[str] | None = None,
    ) -> None:
        self._profiles_dir = get_profiles_dir()
        self._project_dir = project_dir
        self._project_docs_dir = self._project_dir / "docs"
        self._project_config_file = self._project_dir / "dbt_project.yml"
        self._target = target
        self._otlp_service_name = otlp_service_name
        self._otlp_traces_endpoints = otlp_traces_endpoints

        if otlp_traces_endpoints:
            self._tracer = self._init_tracer(self._otlp_service_name, self._otlp_traces_endpoints)
        else:
            self._tracer = None

    def _list_command(
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
        cmd = self._list_command(
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

        if self._tracer:
            raw_command = " ".join(cmd)
            invocation_id = str(uuid4())
            self._trace_invocation(
                self._tracer,
                DbtCommand.RUN,
                raw_command,
                invocation_id,
                runner_result,
                full_refresh=full_refresh,
            )

        return runner_result

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

        if self._tracer:
            raw_command = " ".join(cmd)
            invocation_id = str(uuid4())
            self._trace_invocation(
                self._tracer, DbtCommand.RUN_OPERATION, raw_command, invocation_id, runner_result
            )

        return runner_result

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

        if self._tracer:
            raw_command = " ".join(cmd)
            invocation_id = str(uuid4())
            self._trace_invocation(
                self._tracer, DbtCommand.SEED, raw_command, invocation_id, runner_result
            )

        return runner_result

    def generate_model_yaml(self, models: list[str]):
        """Generate the schema YAML for the given models using dbt-codegen."""
        resources = self.list_resources(resource_types=[DbtResourceType.MODEL])
        selected_resources = pydash.filter_(resources, lambda resource: resource.name in models)

        # Build the models
        model_names = [resource.name for resource in selected_resources]
        self.run(quiet=True, full_refresh=True, models=" ".join(model_names))

        # Generate the schema YAML
        cmd = self._run_operation_command(
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

    def _init_tracer(self, service_name: str, endpoints: list[str]) -> Tracer:
        resource = Resource(attributes={SERVICE_NAME: service_name})
        tracer_provider = TracerProvider(resource=resource)
        set_tracer_provider(tracer_provider)

        for endpoint in endpoints:
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            tracer_provider.add_span_processor(processor)

        return get_tracer(__name__)

    def _trace_invocation(
        self,
        tracer: Tracer,
        command: DbtCommand,
        raw_command: str,
        invocation_id: str,
        runner_result: dbtRunnerResult,
        full_refresh: bool | None = False,
    ):
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
                        node_span.set_status(Status(StatusCode.OK))
                    elif n.status == RunStatus.Error:
                        message = n.message or f"status={n.status}"
                        node_span.record_exception(Exception(message))
                        node_span.set_status(Status(StatusCode.ERROR, message))
                        node_span.add_event("dbt.node.failure", {"failures": int(n.failures or 0)})
                    elif n.status == RunStatus.Skipped:
                        node_span.set_status(Status(StatusCode.UNSET))
                    else:
                        raise Exception(f"Run status '{n.status}' is not supported")

                    # attach the textual message as an event
                    if n.message:
                        node_span.add_event("dbt.node.message", {"message": n.message})

                    # end node span with explicit end_time
                    node_span.end(end_time=to_ns(node_end_dt))

            # now end root span with run end timestamp
            root_span.end(end_time=to_ns(root_end_dt))
