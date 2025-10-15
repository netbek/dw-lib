from .root import app
from dw_lib.peerdb import PeerDB
from typing import Literal

import os
import rich
import typer

peerdb_app = typer.Typer(name="peerdb", add_completion=True)
app.add_typer(peerdb_app)
console = rich.console.Console()


@peerdb_app.command()
def debug(config: str = "peerdb.yaml") -> None:
    """Check the PeerDB configuration and connections."""
    peerdb = PeerDB(os.path.abspath(config))
    peerdb.debug()


@peerdb_app.command()
def up(config: str = "peerdb.yaml", if_exists: Literal["fail", "keep", "replace"] = "fail") -> None:
    """Add PeerDB publications and replication slots to the source database."""
    peerdb = PeerDB(os.path.abspath(config))

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
def down(config: str = "peerdb.yaml", if_exists: bool | None = False) -> None:
    """Remove PeerDB publications and replication slots from the source database, and remove tables from the destination database."""
    peerdb = PeerDB(os.path.abspath(config))

    for peer in peerdb.config.peers:
        response = peerdb.drop_peer(
            peer.name, drop_mirrors=True, drop_destination_tables=True, if_exists=if_exists
        )
        console.print(response.message, style="green")
