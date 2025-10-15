from .root import app
from dw_lib.peerdb import PeerDB
from dw_lib.utils.filesystem import find_up
from pathlib import Path
from typing import Literal

import os
import rich
import typer

peerdb_app = typer.Typer(name="peerdb", add_completion=True)
app.add_typer(peerdb_app)
console = rich.console.Console()


def find_config_file() -> Path:
    cwd = os.getcwd()
    config_file = find_up(cwd, "peerdb.yaml")

    if not config_file:
        raise Exception(f"peerdb.yaml not found in {cwd} or higher")

    return config_file


@peerdb_app.command()
def debug() -> None:
    """Check the PeerDB configuration and connections."""
    config_file = find_config_file()
    peerdb = PeerDB(config_file)
    peerdb.debug()


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
