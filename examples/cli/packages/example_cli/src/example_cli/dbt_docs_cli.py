from dw_lib.dbt import Dbt, find_project_dir

import rich.console
import typer

dbt_docs_app = typer.Typer(name="docs")
console = rich.console.Console()


@dbt_docs_app.command()
def generate():
    """Generate project docs."""
    project_dir = find_project_dir()
    dbt = Dbt(project_dir)
    dbt.docs_generate()
    console.print(f"Generated docs for '{project_dir}'", style="green")


@dbt_docs_app.command()
def serve():
    """Serve project docs."""
    project_dir = find_project_dir()
    dbt = Dbt(project_dir)
    dbt.docs_serve()
