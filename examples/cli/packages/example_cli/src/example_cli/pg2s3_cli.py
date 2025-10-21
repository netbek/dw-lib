from .root import app
from dw_lib.pg2s3 import find_config_file, PG2S3

import rich
import typer

pg2s3_app = typer.Typer(name="pg2s3")
app.add_typer(pg2s3_app)
console = rich.console.Console()


@pg2s3_app.command()
def debug() -> None:
    """Check the configuration and connections."""
    config_file = find_config_file()
    pg2s3 = PG2S3(config_file)
    pg2s3.debug(echo=True)


@pg2s3_app.command()
def run(source_connection: str, destination_connection: str, stream: str) -> None:
    """Run the stream."""
    config_file = find_config_file()
    pg2s3 = PG2S3(config_file)
    response = pg2s3.run(source_connection, destination_connection, stream)
    console.print(response.message, style="green")
