from dw_lib.peerdb import PeerDB
from rich.console import Console

import typer

settings_app = typer.Typer(name="settings", help="Manage settings.", add_completion=False)
console = Console()
peerdb = PeerDB()


@settings_app.command()
def update() -> None:
    """Apply settings from peerdb.yaml."""
    peerdb.update_settings({setting.name: setting.value for setting in peerdb.config.settings})
    console.print("Updated settings", style="green")
