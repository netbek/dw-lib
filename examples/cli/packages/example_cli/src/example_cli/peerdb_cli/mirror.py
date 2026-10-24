from collections.abc import Callable
from dw_lib.exceptions import MirrorNotFoundException
from dw_lib.peerdb import PeerDB
from rich.console import Console
from typing import Any, Literal

import pydash
import typer

mirror_app = typer.Typer(name="mirror", help="Manage mirrors.", add_completion=False)
console = Console()
peerdb = PeerDB()


@mirror_app.command()
def create(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Create all mirrors."),
    if_exists: Literal["fail", "keep", "replace"] = "keep",
) -> None:
    """
    Create a mirror, or all mirrors.

    If keeping existing mirrors, use resync to pick up added or removed columns and changed types.
    """
    _validate_name_or_all(name, all)

    if all:
        _run_batch(
            lambda: peerdb.create_mirrors(
                [mirror.model_dump() for mirror in peerdb.config.mirrors],
                if_exists=if_exists,
            )
        )
    else:
        mirror = pydash.find(peerdb.config.mirrors, lambda x: x.flow_job_name == name)

        if not mirror:
            raise MirrorNotFoundException(f"Mirror '{name}' not found in {peerdb._config_file}")

        response = peerdb.create_mirror(mirror.model_dump(), if_exists=if_exists)
        console.print(response.message, style="green")


@mirror_app.command()
def drop(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Drop all mirrors."),
    drop_destination_tables: bool | None = False,
    if_exists: bool | None = True,
) -> None:
    """Drop a mirror, or all mirrors."""
    _validate_name_or_all(name, all)

    if all:
        _run_batch(
            lambda: peerdb.drop_mirrors(
                [mirror.name for mirror in peerdb.list_mirrors().mirrors],
                drop_destination_tables=drop_destination_tables,
                if_exists=if_exists,
            )
        )
    else:
        response = peerdb.drop_mirror(
            name,
            drop_destination_tables=drop_destination_tables,
            if_exists=if_exists,
        )
        console.print(response.message, style="green")


@mirror_app.command()
def pause(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Pause all running mirrors."),
) -> None:
    """Pause a running mirror, or all running mirrors."""
    _validate_name_or_all(name, all)

    if all:
        _run_batch(
            lambda: peerdb.pause_mirrors([mirror.name for mirror in peerdb.list_mirrors().mirrors])
        )
    else:
        response = peerdb.pause_mirror(name)
        console.print(response.message, style="green")


@mirror_app.command()
def resume(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Resume all paused or pausing mirrors."),
) -> None:
    """Resume a paused or pausing mirror, or all paused or pausing mirrors."""
    _validate_name_or_all(name, all)

    if all:
        _run_batch(
            lambda: peerdb.resume_mirrors([mirror.name for mirror in peerdb.list_mirrors().mirrors])
        )
    else:
        response = peerdb.resume_mirror(name)
        console.print(response.message, style="green")


@mirror_app.command()
def resync(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="Resync all mirrors."),
    if_exists: bool | None = True,
) -> None:
    """
    Resync a mirror, or all mirrors.

    Picks up added or removed columns and changed types.
    """
    _validate_name_or_all(name, all)

    if all:
        _run_batch(
            lambda: peerdb.resync_mirrors(
                [mirror.name for mirror in peerdb.list_mirrors().mirrors],
                if_exists=if_exists,
            )
        )
    else:
        response = peerdb.resync_mirror(name, if_exists=if_exists)
        console.print(response.message, style="green")


def _run_batch(operation: Callable[[], list[Any]]) -> None:
    try:
        responses = operation()
    except Exception as exc:  # noqa: BLE001
        console.print(str(exc), style="red")
        raise typer.Exit(code=1) from exc

    for response in responses:
        console.print(response.message, style="green")


def _validate_name_or_all(name: str | None, all: bool) -> bool:
    if all and name:
        raise typer.BadParameter("Provide a name or --all, not both")
    if not all and not name:
        raise typer.BadParameter("Provide a name or --all")
    return True
