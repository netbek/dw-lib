from .root import app
from dw_lib.loader import find_config_file, Loader

import rich
import typer

loader_app = typer.Typer(name="loader")
app.add_typer(loader_app)
console = rich.console.Console()


@loader_app.command()
def debug() -> None:
    """Check the configuration and connections."""
    config_file = find_config_file()
    loader = Loader(config_file)
    loader.debug(echo=True)


@loader_app.command()
def run(source_connection: str, destination_connection: str, stream: str) -> None:
    """Run the stream."""
    config_file = find_config_file()
    loader = Loader(config_file)
    response = loader.run(source_connection, destination_connection, stream)
    console.print(response.message, style="green")
