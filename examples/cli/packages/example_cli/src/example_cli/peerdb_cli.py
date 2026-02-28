from .root import app
from dw_lib.peerdb import PeerDB
from typing import Literal

import pydash
import rich
import typer

peerdb_app = typer.Typer(name="peerdb")
app.add_typer(peerdb_app)
console = rich.console.Console()
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


@peerdb_app.command()
def update_settings() -> None:
    """Apply settings from peerdb.yaml."""
    peerdb.update_settings({setting.name: setting.value for setting in peerdb.config.settings})
    console.print("Updated settings", style="green")


@peerdb_app.command()
def create_peers(if_exists: Literal["fail", "keep", "replace"] = "keep") -> None:
    """Create all peers, and add replication slots to source database."""
    for peer in peerdb.config.peers:
        response = peerdb.create_peer(
            {"name": peer.name, **peer.peerdb.model_dump()}, if_exists=if_exists
        )
        console.print(response.message, style="green")


@peerdb_app.command()
def drop_peers(drop_destination_tables: bool | None = False, if_exists: bool | None = True) -> None:
    """Drop all peers and mirrors, and remove replication slots from source database."""
    for peer in peerdb.config.peers:
        response = peerdb.drop_peer(
            peer.name,
            drop_mirrors=True,
            drop_destination_tables=drop_destination_tables,
            if_exists=if_exists,
        )
        console.print(response.message, style="green")


@peerdb_app.command()
def create_mirrors(if_exists: Literal["fail", "keep", "replace"] = "keep") -> None:
    """Create all mirrors."""
    for mirror in peerdb.config.mirrors:
        response = peerdb.create_mirror(mirror.model_dump(), if_exists=if_exists)
        console.print(response.message, style="green")


@peerdb_app.command()
def drop_mirrors(
    drop_destination_tables: bool | None = False, if_exists: bool | None = True
) -> None:
    """Drop all mirrors."""
    list_response = peerdb.list_mirrors()
    for mirror in list_response.mirrors:
        response = peerdb.drop_mirror(
            mirror.name,
            drop_destination_tables=drop_destination_tables,
            if_exists=if_exists,
        )
        console.print(response.message, style="green")


@peerdb_app.command()
def resync_mirrors(if_exists: bool | None = True) -> None:
    """Resync all mirrors."""
    list_response = peerdb.list_mirrors()
    for mirror in list_response.mirrors:
        response = peerdb.resync_mirror(mirror.name, if_exists=if_exists)
        console.print(response.message, style="green")


@peerdb_app.command()
def pause_mirrors() -> None:
    """Pause all running mirrors."""
    list_response = peerdb.list_mirrors()
    for mirror in list_response.mirrors:
        response = peerdb.pause_mirror(mirror.name)
        console.print(response.message, style="green")


@peerdb_app.command()
def resume_mirrors() -> None:
    """Resume all paused or pausing mirrors."""
    list_response = peerdb.list_mirrors()
    for mirror in list_response.mirrors:
        response = peerdb.resume_mirror(mirror.name)
        console.print(response.message, style="green")


@peerdb_app.command()
def create_peer(name: str, if_exists: Literal["fail", "keep", "replace"] = "keep") -> None:
    """Create a peer."""
    peer = pydash.find(peerdb.config.peers, lambda x: x.name == name)
    response = peerdb.create_peer(peer.model_dump(), if_exists=if_exists)
    console.print(response.message, style="green")


@peerdb_app.command()
def drop_peer(
    name: str, drop_destination_tables: bool | None = False, if_exists: bool | None = True
) -> None:
    """Drop a peer and its mirrors, and remove replication slot from source database."""
    response = peerdb.drop_peer(
        name,
        drop_mirrors=True,
        drop_destination_tables=drop_destination_tables,
        if_exists=if_exists,
    )
    console.print(response.message, style="green")


@peerdb_app.command()
def create_mirror(name: str, if_exists: Literal["fail", "keep", "replace"] = "keep") -> None:
    """Create a mirror."""
    mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == name)
    response = peerdb.create_mirror(mirror.model_dump(), if_exists=if_exists)
    console.print(response.message, style="green")


@peerdb_app.command()
def drop_mirror(
    name: str,
    drop_destination_tables: bool | None = False,
    if_exists: bool | None = True,
) -> None:
    """Drop a mirror."""
    response = peerdb.drop_mirror(
        name, drop_destination_tables=drop_destination_tables, if_exists=if_exists
    )
    console.print(response.message, style="green")


@peerdb_app.command()
def resync_mirror(name: str, if_exists: bool | None = True) -> None:
    """Resync a mirror."""
    response = peerdb.resync_mirror(name, if_exists=if_exists)
    console.print(response.message, style="green")


@peerdb_app.command()
def pause_mirror(name: str) -> None:
    """Pause a running mirror."""
    response = peerdb.pause_mirror(name)
    console.print(response.message, style="green")


@peerdb_app.command()
def resume_mirror(name: str) -> None:
    """Resume a paused or pausing mirror."""
    response = peerdb.resume_mirror(name)
    console.print(response.message, style="green")
