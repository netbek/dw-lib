from ..utils.filesystem import find_up, get_file_extension
from ..utils.yaml_utils import safe_load_file
from .types import DbtModel, DbtResourceType, DbtSeed, DbtSource
from datetime import datetime, timezone
from dbt.artifacts.schemas.run import RunExecutionResult
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
from typing import Any, Optional
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


# Based on https://github.com/elementary-data/dbt-data-reliability/blob/6551383e8a37e5814bd2bb9fd74330be8265a3c9/models/run_results.yml#L133
class ParsedRunResult(BaseModel):
    model_execution_id: str
    unique_id: str
    invocation_id: str
    generated_at: datetime
    name: str
    message: str | None = None
    status: str
    resource_type: str
    execution_time: float
    compile_started_at: datetime | None = None
    compile_completed_at: datetime | None = None
    execute_started_at: datetime | None = None
    execute_completed_at: datetime | None = None
    rows_affected: int | None = 0
    full_refresh: bool
    compiled_code: str | None = None
    failures: int | None = 0
    query_id: str | None = None
    thread_id: str | None = None
    materialization: str | None = None
    adapter_response: str | None = None


def parse_runner_result(
    invocation_id: str, runner_result: dbtRunnerResult, full_refresh: bool | None = False
) -> list[ParsedRunResult]:
    def _normalize_rows_affected(value) -> int | None:
        if value is None:
            return None
        elif isinstance(value, int):
            return value
        elif isinstance(value, str) and value.isdigit():
            if value == "-1":
                return None
            else:
                return int(value)
        else:
            return None

    parsed_run_results = []
    execution_result: RunExecutionResult = runner_result.result

    for run_result in execution_result.results:
        compile_started_at = None
        compile_completed_at = None
        execute_started_at = None
        execute_completed_at = None

        for timing_info in run_result.timing:
            if timing_info.name == "compile":
                compile_started_at = timing_info.started_at
                compile_completed_at = timing_info.completed_at
            elif timing_info.name == "execute":
                execute_started_at = timing_info.started_at
                execute_completed_at = timing_info.completed_at

        if isinstance(run_result.node, ModelNode):
            compiled_code = run_result.node.compiled_code
        else:
            compiled_code = None

        parsed_run_result = ParsedRunResult(
            model_execution_id=f"{invocation_id}.{run_result.node.unique_id}",
            unique_id=run_result.node.unique_id,
            invocation_id=invocation_id,
            generated_at=execution_result.generated_at,
            name=run_result.node.name,
            message=run_result.message,
            status=run_result.status,
            resource_type=run_result.node.resource_type,
            execution_time=run_result.execution_time,
            compile_started_at=compile_started_at,
            compile_completed_at=compile_completed_at,
            execute_started_at=execute_started_at,
            execute_completed_at=execute_completed_at,
            rows_affected=_normalize_rows_affected(
                run_result.adapter_response.get("rows_affected")
            ),
            full_refresh=full_refresh,
            compiled_code=compiled_code,
            failures=run_result.failures,
            query_id=run_result.adapter_response.get("query_id"),
            thread_id=run_result.thread_id,
            materialization=run_result.node.config.materialized,
            adapter_response=json.dumps(run_result.adapter_response),
        )
        parsed_run_results.append(parsed_run_result)

    return parsed_run_results


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
            self._trace_runner_result(
                self._tracer, raw_command, invocation_id, runner_result, full_refresh=full_refresh
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

        return dbtRunner().invoke(cmd[1:])

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
            self._trace_runner_result(self._tracer, raw_command, invocation_id, runner_result)

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

    def _trace_runner_result(
        self,
        tracer: Tracer,
        raw_command: str,
        invocation_id: str,
        runner_result: dbtRunnerResult,
        full_refresh: bool | None = False,
    ):
        parsed_run_results = parse_runner_result(
            invocation_id, runner_result, full_refresh=full_refresh
        )

        if not parsed_run_results:
            return

        def _to_ns(dt: datetime) -> int:
            """Convert a timezone-aware (or naive assumed UTC) datetime to nanoseconds since epoch."""
            if dt is None:
                raise ValueError("dt is None")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000_000)

        def _safe_str(s: str | None, max_len: int = 200) -> str | None:
            if s is None:
                return None
            if len(s) <= max_len:
                return s
            return s[:max_len] + "...(truncated)"

        # compute root start/end from model timestamps if available
        def _min_datetime(*datetimes):
            vals = [d for d in datetimes if d is not None]
            return min(vals) if vals else None

        def _max_datetime(*datetimes):
            vals = [d for d in datetimes if d is not None]
            return max(vals) if vals else None

        run_start_dt = _min_datetime(
            *[r.compile_started_at for r in parsed_run_results],
            *[r.execute_started_at for r in parsed_run_results],
            *[r.generated_at for r in parsed_run_results],
        )
        run_end_dt = _max_datetime(
            *[r.compile_completed_at for r in parsed_run_results],
            *[r.execute_completed_at for r in parsed_run_results],
            *[r.generated_at for r in parsed_run_results],
        )

        run_start_ns = (
            _to_ns(run_start_dt)
            if run_start_dt
            else int(_to_ns(parsed_run_results[0].generated_at))
        )
        run_end_ns = (
            _to_ns(run_end_dt)
            if run_end_dt
            else run_start_ns
            + int(sum(max(0.0, r.execution_time) for r in parsed_run_results) * 1_000_000_000)
        )

        root_attrs = {
            "dbt.invocation_id": invocation_id,
            "dbt.raw_command": raw_command,
            "dbt.run.model_count": len(parsed_run_results),
            "dbt.run.generated_at": parsed_run_results[0].generated_at.isoformat(),
        }

        # create root span but don't end it automatically; we want to set custom end_time
        with tracer.start_as_current_span(
            f"dbt.run {invocation_id}",
            attributes=root_attrs,
            start_time=run_start_ns,
            end_on_exit=False,
        ) as root_span:
            # iterate models and create child spans
            for r in parsed_run_results:
                # choose model start/end; prefer execute timestamps
                model_start_dt = r.execute_started_at or r.compile_started_at or r.generated_at
                model_end_dt = (
                    r.execute_completed_at
                    or r.compile_completed_at
                    or (model_start_dt if model_start_dt else r.generated_at)
                )
                model_start_ns = _to_ns(model_start_dt)
                model_end_ns = _to_ns(model_end_dt)

                model_attrs = {
                    "dbt.model.unique_id": r.unique_id,
                    "dbt.model.name": r.name,
                    "dbt.model.resource_type": r.resource_type,
                    "dbt.model.materialization": r.materialization or "",
                    "dbt.model.execution_time_s": float(r.execution_time or 0.0),
                    "dbt.model.rows_affected": int(r.rows_affected or 0),
                    "dbt.model.full_refresh": bool(r.full_refresh),
                    "dbt.model.query_id": r.query_id or "",
                    "dbt.model.thread_id": r.thread_id or "",
                }

                # keep largest text fields trimmed
                if r.adapter_response:
                    model_attrs["dbt.model.adapter_response_excerpt"] = _safe_str(
                        r.adapter_response, 200
                    )

                # start model span with explicit timestamp and don't end on exit so we can set end_time
                with tracer.start_as_current_span(
                    f"dbt.model {r.name}",
                    attributes=model_attrs,
                    start_time=model_start_ns,
                    end_on_exit=False,
                ) as model_span:
                    # record compile nested span if we have timestamps
                    if r.compile_started_at and r.compile_completed_at:
                        cs_ns = _to_ns(r.compile_started_at)
                        ce_ns = _to_ns(r.compile_completed_at)
                        with tracer.start_as_current_span(
                            "dbt.model.compile",
                            start_time=cs_ns,
                            end_on_exit=False,
                        ) as compile_span:
                            compile_span.set_attribute(
                                "dbt.compile.duration_s", (ce_ns - cs_ns) / 1e9
                            )
                            compile_span.end(end_time=ce_ns)

                    # record execute nested span if we have timestamps
                    if r.execute_started_at and r.execute_completed_at:
                        es_ns = _to_ns(r.execute_started_at)
                        ee_ns = _to_ns(r.execute_completed_at)
                        with tracer.start_as_current_span(
                            "dbt.model.execute",
                            start_time=es_ns,
                            end_on_exit=False,
                        ) as exec_span:
                            exec_span.set_attribute("dbt.execute.duration_s", (ee_ns - es_ns) / 1e9)
                            exec_span.end(end_time=ee_ns)

                    # failures / status handling
                    if (r.failures or 0) > 0 or (
                        r.status and r.status.lower() not in ("success", "ok")
                    ):
                        msg = r.message or f"status={r.status}"
                        model_span.record_exception(Exception(msg))
                        # set error status so it's visible in traces
                        model_span.set_status(Status(StatusCode.ERROR, str(msg)))
                        model_span.add_event(
                            "dbt.model.failure",
                            {"failures": int(r.failures or 0), "msg": _safe_str(msg, 200)},
                        )
                    else:
                        # leaving status unset (Unset) is normal for success; set OK only if you want explicit OK
                        model_span.set_status(Status(StatusCode.UNSET))

                    # attach the textual message as an event (trimmed)
                    if r.message:
                        model_span.add_event(
                            "dbt.message", {"message_excerpt": _safe_str(r.message, 200)}
                        )

                    # end model span with explicit end_time
                    model_span.end(end_time=model_end_ns)

            # now end root span with run end timestamp
            root_span.end(end_time=run_end_ns)
