from ..root import app
from .mirror import mirror_app
from .peer import peer_app
from .settings import settings_app
from dw_lib.peerdb import PeerDB
from rich.console import Console
from typing import Literal

import typer

peerdb_app = typer.Typer(name="peerdb", add_completion=False)
app.add_typer(peerdb_app)
peerdb_app.add_typer(settings_app)
peerdb_app.add_typer(peer_app)
peerdb_app.add_typer(mirror_app)
console = Console()
peerdb = PeerDB()


@peerdb_app.command()
def debug() -> None:
    """Check the configuration, connections, publications, and replication slots."""
    peerdb.debug(echo=True)


@peerdb_app.command()
def up(if_exists: Literal["fail", "keep", "replace"] = "keep") -> None:
    """Create all peers and mirrors, and add replication slots to the source database."""
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
