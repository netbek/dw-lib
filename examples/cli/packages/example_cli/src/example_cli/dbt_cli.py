from .dbt_docs_cli import dbt_docs_app
from .root import app
from dw_lib.dbt import Dbt, find_project_dir

import dbt.version
import rich
import typer

dbt_app = typer.Typer(name="dbt")
dbt_app.add_typer(dbt_docs_app)
app.add_typer(dbt_app)
console = rich.console.Console()


@dbt_app.command()
def version():
    """Print dbt version."""
    console.print(dbt.version.__version__)


@dbt_app.command()
def resources():
    """List project resources."""
    project_dir = find_project_dir()
    dbt = Dbt(project_dir)
    for resource in dbt.list_resources():
        print(f"{resource.resource_type}: {resource.name}")


@dbt_app.command()
def model_yaml(models: list[str]):
    """Generate dbt model schema YAML."""
    project_dir = find_project_dir()
    dbt = Dbt(project_dir)
    dbt.generate_model_yaml(models)
    console.print(f"Generated schema YAML for: {', '.join(models)}", style="green")


@dbt_app.command()
def run():
    """Compile SQL and execute against the current target database."""
    project_dir = find_project_dir()
    dbt = Dbt(project_dir)
    dbt.run()


@dbt_app.command()
def seed():
    """Load data from CSV files into your data warehouse."""
    project_dir = find_project_dir()
    dbt = Dbt(
        project_dir, otlp_traces_endpoints=["http://localhost:20428/insert/opentelemetry/v1/traces"]
    )
    dbt.seed()
