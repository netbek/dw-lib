from .constants import CODEGEN_TO_CLICKHOUSE_DATA_TYPE
from .types import DbtModel, DbtResourceType, DbtSeed, DbtSource
from .utils.filesystem import find_up, get_file_extension
from .utils.yaml_utils import safe_load_file
from dbt.cli.main import dbtRunner, dbtRunnerResult
from livereload import Server
from pathlib import Path
from typing import Any

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


def resolve_resource_path(project_dir: Path | str, resource: dict) -> Path | None:
    project_dir = Path(project_dir)
    project_name = project_dir.name

    if resource["package_name"] == project_name:
        path = project_dir / resource["original_file_path"]
    else:
        path = project_dir / "dbt_packages" / resource["original_file_path"]

    if path.exists():
        return path


def bundle_docs(project_dir: Path) -> None:
    """
    Transform output from `dbt docs generate` into a single HTML file.

    Source: https://data-banana.github.io/dbt-generate-doc-in-one-static-html-file.html
    """
    html_path = project_dir / "target" / "index.html"
    manifest_path = project_dir / "target" / "manifest.json"
    catalog_path = project_dir / "target" / "catalog.json"
    dest_path = project_dir / "docs" / "index.html"

    with open(html_path) as fp:
        html = fp.read()

    with open(manifest_path) as fp:
        manifest = json.load(fp)

    with open(catalog_path) as fp:
        catalog = json.load(fp)

    search_str = 'n=[o("manifest","manifest.json"+t),o("catalog","catalog.json"+t)]'
    replace_str = (
        "n=[{label: 'manifest', data: "
        + json.dumps(manifest)
        + "},{label: 'catalog', data: "
        + json.dumps(catalog)
        + "}]"
    )
    html = html.replace(search_str, replace_str)

    os.makedirs(dest_path.parent, exist_ok=True)
    with open(dest_path, "w") as fp:
        fp.write(html)


class Dbt:
    def __init__(self, project_dir: Path | str, target: str | None = None) -> None:
        self._profiles_dir = get_profiles_dir()
        self._project_dir = Path(project_dir)
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
    ) -> dbtRunnerResult:
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
        bundle_docs(self._project_dir)

        return result

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
