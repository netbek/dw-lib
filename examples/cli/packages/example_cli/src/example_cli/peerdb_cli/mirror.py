from dw_lib.exceptions import MirrorNotFoundException
from dw_lib.peerdb import PeerDB
from rich.console import Console
from typing import Literal

import pydash
import typer

mirror_app = typer.Typer(name="mirror", help="Manage mirrors.", add_completion=False)
console = Console()
peerdb = PeerDB()


@mirror_app.command()
def create(
    name: str = typer.Argument(None, help="Name of the mirror in the config."),
    all: bool = typer.Option(False, "--all", help="Create all mirrors."),
    if_exists: Literal["fail", "keep", "replace"] = typer.Option(
        "keep", help="Behavior when the mirror already exists: fail, keep, or replace."
    ),
    wait: bool = typer.Option(
        False,
        "--wait/--no-wait",
        help=(
            "Wait for the initial snapshot to finish. Without --wait, return after PeerDB "
            "accepts the request."
        ),
    ),
) -> None:
    """
    Create a mirror, or all mirrors.

    If keeping existing mirrors, use resync to pick up added or removed columns and changed types.
    """
    _validate_name_or_all(name, all)

    if all:
        for mirror in peerdb.config.mirrors:
            response = peerdb.create_mirror(mirror.model_dump(), if_exists=if_exists, wait=wait)
            console.print(response.message, style="green")
    else:
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == name)

        if not mirror:
            raise MirrorNotFoundException(f"Mirror '{name}' not found in {peerdb._config_file}")

        response = peerdb.create_mirror(mirror.model_dump(), if_exists=if_exists, wait=wait)
        console.print(response.message, style="green")


@mirror_app.command()
def drop(
    name: str = typer.Argument(None, help="Name of the mirror to drop."),
    all: bool = typer.Option(False, "--all", help="Drop all mirrors."),
    drop_destination_tables: bool | None = typer.Option(
        False, help="Drop destination tables after dropping the mirror."
    ),
    if_exists: bool | None = typer.Option(True, help="Skip missing mirrors instead of raising."),
) -> None:
    """Drop a mirror, or all mirrors."""
    _validate_name_or_all(name, all)

    if all:
        list_response = peerdb.list_mirrors()
        for mirror in list_response.mirrors:
            response = peerdb.drop_mirror(
                mirror.name,
                drop_destination_tables=drop_destination_tables,
                if_exists=if_exists,
            )
            console.print(response.message, style="green")
    else:
        response = peerdb.drop_mirror(
            name,
            drop_destination_tables=drop_destination_tables,
            if_exists=if_exists,
        )
        console.print(response.message, style="green")


@mirror_app.command()
def pause(
    name: str = typer.Argument(None, help="Name of the mirror to pause."),
    all: bool = typer.Option(False, "--all", help="Pause all running mirrors."),
) -> None:
    """Pause a running mirror, or all running mirrors."""
    _validate_name_or_all(name, all)

    if all:
        list_response = peerdb.list_mirrors()
        for mirror in list_response.mirrors:
            response = peerdb.pause_mirror(mirror.name)
            console.print(response.message, style="green")
    else:
        response = peerdb.pause_mirror(name)
        console.print(response.message, style="green")


@mirror_app.command()
def resume(
    name: str = typer.Argument(None, help="Name of the mirror to resume."),
    all: bool = typer.Option(False, "--all", help="Resume all paused or pausing mirrors."),
) -> None:
    """Resume a paused or pausing mirror, or all paused or pausing mirrors."""
    _validate_name_or_all(name, all)

    if all:
        list_response = peerdb.list_mirrors()
        for mirror in list_response.mirrors:
            response = peerdb.resume_mirror(mirror.name)
            console.print(response.message, style="green")
    else:
        response = peerdb.resume_mirror(name)
        console.print(response.message, style="green")


@mirror_app.command()
def resync(
    name: str = typer.Argument(None, help="Name of the mirror to resync."),
    all: bool = typer.Option(False, "--all", help="Resync all mirrors."),
    if_exists: bool | None = typer.Option(True, help="Skip missing mirrors instead of raising."),
    wait: bool = typer.Option(
        False,
        "--wait/--no-wait",
        help=("Wait for the resync snapshot to finish. Without --wait, wait for STATUS_RESYNC."),
    ),
) -> None:
    """
    Resync a mirror, or all mirrors.

    Picks up added or removed columns and changed types.
    """
    _validate_name_or_all(name, all)

    if all:
        list_response = peerdb.list_mirrors()
        for mirror in list_response.mirrors:
            response = peerdb.resync_mirror(mirror.name, if_exists=if_exists, wait=wait)
            console.print(response.message, style="green")
    else:
        response = peerdb.resync_mirror(name, if_exists=if_exists, wait=wait)
        console.print(response.message, style="green")


def _validate_name_or_all(name: str | None, all: bool) -> bool:
    if all and name:
        raise typer.BadParameter("Provide a name or --all, not both")
    if not all and not name:
        raise typer.BadParameter("Provide a name or --all")
    return True
