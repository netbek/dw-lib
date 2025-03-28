from ..constants import PEERDB_DESTINATION_PEER, PEERDB_SOURCE_PEER
from ..peerdb import DestinationPeer, PeerDB, SourcePeer
from ..project import Project
from ..types import PostgresTableIdentifier
from ..utils.typer_utils import typer_async
from .root import app

import typer

peerdb_app = typer.Typer(name="peerdb", add_completion=False)
app.add_typer(peerdb_app)


@peerdb_app.command()
@typer_async
async def install(project_name: str) -> None:
    project = Project.from_name(project_name)
    peerdb = PeerDB(project.settings.peerdb.config_path)
    source_peer = SourcePeer(project.settings.source_db)
    destination_peer = DestinationPeer(
        project.settings.destination_db,
        peerdb.config["peers"][PEERDB_DESTINATION_PEER]["clickhouse_config"]["database"],
    )
    source_user = peerdb.config["users"].get(PEERDB_SOURCE_PEER)

    peerdb.update_settings(peerdb.config["settings"])
    app.console.print("Updated PeerDB settings", style="green")

    if source_user:
        source_peer.create_user(**source_user)
        app.console.print(
            f"Created user '{source_user['username']}' on source",
            style="green",
        )

        for schema in peerdb.config["publication_schemas"]:
            source_peer.grant_user_privileges(source_user["username"], schema)
            app.console.print(
                f"Granted privileges to user '{source_user['username']}' on source schema '{schema}'",
                style="green",
            )

    for mirror in peerdb.config["mirrors"].values():
        for table_mapping in mirror["table_mappings"]:
            if "replica_identity" in table_mapping:
                source_table_identifier = PostgresTableIdentifier.from_string(
                    table_mapping["source_table_identifier"]
                )
                source_peer.set_table_replica_identity(
                    source_table_identifier.table,
                    table_mapping["replica_identity"],
                    database=source_table_identifier.database,
                    schema=source_table_identifier.schema_,
                )
                app.console.print(
                    f"Set replica identity of '{table_mapping['source_table_identifier']}' to '{table_mapping['replica_identity']}'",
                    style="green",
                )

    for publication in peerdb.config["publications"].values():
        source_peer.create_publication(
            publication["name"], publication["table_identifiers"], replace=True
        )
        app.console.print(
            f"Created publication '{publication['name']}' on source",
            style="green",
        )

    destination_peer.create_database(destination_peer.database)
    app.console.print(
        f"Created database '{destination_peer.database}' on destination",
        style="green",
    )

    for peer in peerdb.config["peers"].values():
        peerdb.create_peer(peer)
        app.console.print(
            f"Created PeerDB peer '{peer['name']}'",
            style="green",
        )

    for mirror in peerdb.config["mirrors"].values():
        peerdb.create_mirror(mirror)
        app.console.print(
            f"Created PeerDB mirror '{mirror['flow_job_name']}'",
            style="green",
        )


@peerdb_app.command()
@typer_async
async def uninstall(project_name: str) -> None:
    project = Project.from_name(project_name)
    peerdb = PeerDB(project.settings.peerdb.config_path)
    source_peer = SourcePeer(project.settings.source_db)
    destination_peer = DestinationPeer(
        project.settings.destination_db,
        peerdb.config["peers"][PEERDB_DESTINATION_PEER]["clickhouse_config"]["database"],
    )
    source_user = peerdb.config["users"].get(PEERDB_SOURCE_PEER)

    for mirror in peerdb.config["mirrors"].values():
        peerdb.drop_mirror(mirror)
        app.console.print(
            f"Dropped PeerDB mirror '{mirror['flow_job_name']}'",
            style="green",
        )

    for peer in peerdb.config["peers"].values():
        peerdb.drop_peer(peer)
        app.console.print(
            f"Dropped PeerDB peer '{peer['name']}'",
            style="green",
        )

    for publication in peerdb.config["publications"].values():
        source_peer.drop_publication(publication["name"])
        app.console.print(
            f"Dropped publication '{publication['name']}' on source",
            style="green",
        )

    for mirror in peerdb.config["mirrors"].values():
        for table_mapping in mirror["table_mappings"]:
            if "replica_identity" in table_mapping:
                source_table_identifier = PostgresTableIdentifier.from_string(
                    table_mapping["source_table_identifier"]
                )
                replica_identity = "default"
                source_peer.set_table_replica_identity(
                    source_table_identifier.table,
                    replica_identity,
                    database=source_table_identifier.database,
                    schema=source_table_identifier.schema_,
                )
                app.console.print(
                    f"Set replica identity of '{table_mapping['source_table_identifier']}' to '{replica_identity}'",
                    style="green",
                )

    if source_user:
        for schema in peerdb.config["publication_schemas"]:
            source_peer.revoke_user_privileges(source_user["username"], schema)
            app.console.print(
                f"Revoked privileges from user '{source_user['username']}' on source schema '{schema}'",
                style="green",
            )

        source_peer.drop_user(source_user["username"])
        app.console.print(
            f"Dropped user '{source_user['username']}' on source",
            style="green",
        )

    destination_peer.drop_database(destination_peer.database)
    app.console.print(
        f"Dropped database '{destination_peer.database}' on destination",
        style="green",
    )
