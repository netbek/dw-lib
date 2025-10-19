from .root import app
from dw_lib.peerdb import find_config_file, PeerDB
from typing import Literal

import rich
import typer

peerdb_app = typer.Typer(name="peerdb")
app.add_typer(peerdb_app)
console = rich.console.Console()


@peerdb_app.command()
def debug() -> None:
    """Check the PeerDB configuration and connections."""
    config_file = find_config_file()
    peerdb = PeerDB(config_file)
    peerdb.debug(print=True)


@peerdb_app.command()
def up(if_exists: Literal["fail", "keep", "replace"] = "fail") -> None:
    """Add PeerDB publications and replication slots to the source database."""
    config_file = find_config_file()
    peerdb = PeerDB(config_file)

    peerdb.update_settings({setting.name: setting.value for setting in peerdb.config.settings})
    console.print("Updated settings", style="green")

    for peer in peerdb.config.peers:
        response = peerdb.create_peer(
            {"name": peer.name, **peer.peerdb.model_dump()}, if_exists=if_exists
        )
        console.print(response.message, style="green")

    for mirror in peerdb.config.mirrors:
        response = peerdb.create_mirror(mirror.model_dump(), if_exists=if_exists)
        console.print(response.message, style="green")


@peerdb_app.command()
def down(if_exists: bool | None = False) -> None:
    """Remove PeerDB publications and replication slots from the source database, and remove tables from the destination database."""
    config_file = find_config_file()
    peerdb = PeerDB(config_file)

    for peer in peerdb.config.peers:
        response = peerdb.drop_peer(
            peer.name, drop_mirrors=True, drop_destination_tables=True, if_exists=if_exists
        )
        console.print(response.message, style="green")
