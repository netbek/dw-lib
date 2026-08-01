from dw_lib.exceptions import PeerNotFoundException
from dw_lib.peerdb import PeerDB
from rich.console import Console
from typing import Literal

import pydash
import typer

peer_app = typer.Typer(name="peer", help="Manage peers.", add_completion=False)
console = Console()
peerdb = PeerDB()


@peer_app.command()
def create(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Create all peers."),
    if_exists: Literal["fail", "keep", "replace"] = "keep",
) -> None:
    """Create a peer, or all peers."""
    _validate_name_or_all(name, all)

    if all:
        for peer in peerdb.config.peers:
            response = peerdb.create_peer(
                {"name": peer.name, **peer.peerdb.model_dump()}, if_exists=if_exists
            )
            console.print(response.message, style="green")
    else:
        peer = pydash.find(peerdb.config.peers, lambda x: x.name == name)

        if not peer:
            raise PeerNotFoundException(f"Peer '{name}' not found in {peerdb._config_file}")

        response = peerdb.create_peer(
            {"name": peer.name, **peer.peerdb.model_dump()}, if_exists=if_exists
        )
        console.print(response.message, style="green")


@peer_app.command()
def drop(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Drop all peers."),
    drop_destination_tables: bool | None = False,
    if_exists: bool | None = True,
) -> None:
    """Drop a peer and its mirrors, or all peers and mirrors."""
    _validate_name_or_all(name, all)

    if all:
        for peer in peerdb.config.peers:
            response = peerdb.drop_peer(
                peer.name,
                drop_mirrors=True,
                drop_destination_tables=drop_destination_tables,
                if_exists=if_exists,
            )
            console.print(response.message, style="green")
    else:
        response = peerdb.drop_peer(
            name,
            drop_mirrors=True,
            drop_destination_tables=drop_destination_tables,
            if_exists=if_exists,
        )
        console.print(response.message, style="green")


def _validate_name_or_all(name: str | None, all: bool) -> bool:
    if all and name:
        raise typer.BadParameter("Provide a name or --all, not both")
    if not all and not name:
        raise typer.BadParameter("Provide a name or --all")
    return True
