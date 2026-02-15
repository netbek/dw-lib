from dw_lib.dbt import Dbt

import rich.console
import typer

dbt_docs_app = typer.Typer(name="docs")
console = rich.console.Console()


@dbt_docs_app.command()
def generate():
    """Generate project docs."""
    dbt = Dbt()
    dbt.docs_generate()
    console.print(f"Generated docs for '{dbt._project_dir}'", style="green")


@dbt_docs_app.command()
def serve():
    """Serve project docs."""
    dbt = Dbt()
    dbt.docs_serve()
