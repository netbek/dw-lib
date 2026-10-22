from collections.abc import Callable
from dw_lib.peerdb import CreateMirrorResponse, PeerDB, ResyncMirrorResponse
from rich.console import Console
from typing import Literal

import datetime

console = Console()
peerdb = PeerDB()


def _status_printer(flow_job_name: str) -> Callable[[str, float], None]:
    def on_status_change(status: str, elapsed: float) -> None:
        console.print(
            f"Mirror '{flow_job_name}' is {status} after {datetime.timedelta(seconds=int(elapsed))}",
            style="yellow",
        )

    return on_status_change


def create_mirror(
    mirror: dict,
    if_exists: Literal["fail", "keep", "replace"] = "keep",
    parallel: bool = False,
) -> CreateMirrorResponse:
    """Create a mirror and wait for it to become ready unless parallel mode is enabled."""
    response = peerdb.create_mirror(mirror, if_exists=if_exists)
    console.print(response.message, style="green")

    if not parallel and response.response is not None:
        flow_job_name = mirror["flow_job_name"]
        console.print(f"Waiting for mirror '{flow_job_name}' to become ready", style="yellow")
        peerdb.wait_for_mirror_ready(flow_job_name, on_status_change=_status_printer(flow_job_name))
        console.print(f"Mirror '{flow_job_name}' is ready", style="green")

    return response


def resync_mirror(
    flow_job_name: str,
    if_exists: bool | None = True,
    parallel: bool = False,
) -> ResyncMirrorResponse:
    """Resync a mirror and wait for it to become ready unless parallel mode is enabled."""
    response = peerdb.resync_mirror(
        flow_job_name,
        if_exists=if_exists,
        wait=not parallel,
        on_status_change=_status_printer(flow_job_name),
    )
    console.print(response.message, style="green")

    if not parallel and peerdb.has_mirror(flow_job_name):
        console.print(
            f"Resync accepted; waiting for mirror '{flow_job_name}' to become ready",
            style="yellow",
        )
        peerdb.wait_for_mirror_ready(flow_job_name, on_status_change=_status_printer(flow_job_name))
        console.print(f"Mirror '{flow_job_name}' is ready", style="green")

    return response
