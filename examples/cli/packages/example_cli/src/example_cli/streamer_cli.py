from .root import app
from dw_lib.streamer import find_config_file, Streamer

import rich
import typer

streamer_app = typer.Typer(name="streamer")
app.add_typer(streamer_app)
console = rich.console.Console()


@streamer_app.command()
def debug() -> None:
    """Check the configuration and connections."""
    config_file = find_config_file()
    streamer = Streamer(config_file)
    streamer.debug(echo=True)


@streamer_app.command()
def run(source_connection: str, destination_connection: str, stream: str) -> None:
    """Run the stream."""
    config_file = find_config_file()
    streamer = Streamer(config_file)
    response = streamer.run(source_connection, destination_connection, stream)
    console.print(response.message, style="green")
