from .dbt_docs_cli import dbt_docs_app
from .root import app
from dw_lib.constants import CODEGEN_TO_CLICKHOUSE_DATA_TYPE
from dw_lib.dbt import Dbt
from dw_lib.types import DbtResourceType
from dw_lib.utils.filesystem import find_up
from dw_lib.utils.yaml_utils import safe_load_file
from pathlib import Path

import dbt.version
import json
import os
import pydash
import rich
import subprocess
import typer
import yaml

dbt_app = typer.Typer(name="dbt", add_completion=True)
dbt_app.add_typer(dbt_docs_app)
app.add_typer(dbt_app)
console = rich.console.Console()


def find_project_config_file() -> Path:
    cwd = os.getcwd()
    project_config_file = find_up(cwd, "dbt_project.yml")

    if not project_config_file:
        raise Exception(f"dbt_project.yml not found in {cwd} or higher")

    return project_config_file


@dbt_app.command()
def version():
    """Print dbt version."""
    console.print(dbt.version.__version__)


@dbt_app.command()
def resources():
    """List dbt project resources."""
    project_dir = find_project_config_file().parent
    dbt = Dbt(project_dir)
    resources = dbt.list_resources()

    for resource in resources:
        print(f"{resource.resource_type}: {resource.name}")


@dbt_app.command()
def model_yaml(models: list[str]):
    """Generate dbt model YAML."""
    project_dir = find_project_config_file().parent
    dbt = Dbt(project_dir)
    resources = dbt.list_resources(resource_types=[DbtResourceType.MODEL])

    for model in models:
        resource = pydash.find(resources, lambda resource: resource.name == model)

        if not resource:
            continue

        model_name = resource.name
        model_path = project_dir / resource.original_file_path
        schema_path = model_path.parent / f"{model_name}.yml"
        schema_dir = schema_path.parent

        os.makedirs(schema_dir, exist_ok=True)

        # Load existing schema
        if schema_path.exists():
            schema = safe_load_file(schema_path)
        else:
            schema = {"version": 2, "models": []}

        # Build model
        cmd = [
            "dbt",
            "--fail-fast",
            "--quiet",
            "run",
            "-m",
            model_name,
            "--full-refresh",
        ]
        try:
            subprocess.check_output(cmd, cwd=project_dir)
        except subprocess.CalledProcessError as exc:
            output = exc.output.decode().strip()
            console.print(output, style="red")
            raise exc

        # Generate schema YAML
        # Source: https://github.com/dbt-labs/dbt-codegen/blob/f6666ca441af7cbc01c02eb0e2b32043a9f412a7/README.md#generate_model_yaml-source
        cmd = [
            "dbt",
            "--quiet",
            "run-operation",
            "generate_model_yaml",
            "--args",
            json.dumps({"model_names": [model_name]}),
        ]
        try:
            output = subprocess.check_output(cmd, cwd=project_dir).decode().strip()
        except subprocess.CalledProcessError as exc:
            output = exc.output.decode().strip()
            console.print(output, style="red")
            raise exc

        new_model = yaml.safe_load(output)["models"][0]
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

        schema["models"] = sorted(schema["models"], key=lambda x: x["name"])

        # Write schema file
        with open(schema_path, "w") as fp:
            data = yaml.safe_dump(schema, sort_keys=False)
            fp.write(data)
