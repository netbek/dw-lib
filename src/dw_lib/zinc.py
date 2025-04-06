from .database.adapters.duckdb import DuckDBAdapter
from .database.adapters.postgres import PostgresAdapter
from .types import (
    AdapterType,
    DuckDBTableIdentifier,
    PostgresIdentifier,
    PostgresTableIdentifier,
    ZincMirrorSettings,
    ZincSettings,
)


class Zinc:
    settings: ZincSettings = None
    peers: dict[str, DuckDBAdapter | PostgresAdapter] = {}

    def __init__(self, settings: dict | ZincSettings) -> None:
        if isinstance(settings, ZincSettings):
            self.settings = settings
        else:
            self.settings = ZincSettings(**settings)

        for peer_name, peer_settings in self.settings.peers.items():
            if peer_settings.type == AdapterType.DUCKDB:
                peer_class = DuckDBAdapter
            elif peer_settings.type == AdapterType.POSTGRES:
                peer_class = PostgresAdapter
            else:
                raise ValueError(f"Peer type '{peer_settings.type}' is not suppported.")

            self.peers[peer_name] = peer_class(peer_settings)

    def can_connect(self) -> bool:
        return all([peer.can_connect() for peer in self.peers.values()])

    def _mirror_postgres_to_duckdb(self, mirror: ZincMirrorSettings):
        source_peer: PostgresAdapter = self.peers[mirror.peers.source]
        destination_peer: DuckDBAdapter = self.peers[mirror.peers.destination]

        postgres_url = source_peer.url.render_as_string(hide_password=False)
        postgres_alias = mirror.peers.source
        postgres_schema = PostgresTableIdentifier.from_string(mirror.tables[0].source).schema_

        with destination_peer.create_client() as conn:
            # Attach Postgres
            statement = f"""
            attach '{postgres_url}' as {PostgresIdentifier.quote(postgres_alias)} (type postgres, schema {PostgresIdentifier.quote(postgres_schema)}, read_only);
            """
            conn.execute(statement)

            for table in mirror.tables:
                source_table = PostgresTableIdentifier.from_string(table.source)
                destination_table = DuckDBTableIdentifier.from_string(table.destination)

                if table.query:
                    query = table.query
                else:
                    query = f"select * from {source_table.to_string()}"
                query = query.strip().strip(";")

                # Copy table
                statement = f"""
                drop table if exists {destination_table.to_string()};
                create table {destination_table.to_string()} as {query};
                """
                conn.execute(statement)

            # Detach Postgres
            statement = f"""
            detach {PostgresIdentifier.quote(postgres_alias)};
            """
            conn.execute(statement)

    def _mirror_duckdb_to_postgres(self, mirror: ZincMirrorSettings):
        source_peer: DuckDBAdapter = self.peers[mirror.peers.source]
        destination_peer: PostgresAdapter = self.peers[mirror.peers.destination]

        postgres_url = destination_peer.url.render_as_string(hide_password=False)
        postgres_alias = mirror.peers.destination
        postgres_schema = PostgresTableIdentifier.from_string(mirror.tables[0].destination).schema_

        with source_peer.create_client() as conn:
            # Attach Postgres
            statement = f"""
            attach '{postgres_url}' as {PostgresIdentifier.quote(postgres_alias)} (type postgres, schema {PostgresIdentifier.quote(postgres_schema)});
            """
            conn.execute(statement)

            for table in mirror.tables:
                source_table = DuckDBTableIdentifier.from_string(table.source)
                destination_table = PostgresTableIdentifier.from_string(table.destination)

                if table.query:
                    query = table.query
                else:
                    query = f"select * from {source_table.to_string()}"
                query = query.strip().strip(";")

                # Copy table
                statement = f"""
                drop table if exists {destination_table.to_string()};
                create table {destination_table.to_string()} as {query};
                """
                conn.execute(statement)

                # Create indexes
                for index in table.indexes:
                    statement = f"""
                    create index {index.name} on {destination_table.to_string()} using {index.type} ({", ".join(index.columns)});
                    """
                    conn.execute(statement)

            # Detach Postgres
            statement = f"""
            detach {PostgresIdentifier.quote(postgres_alias)};
            """
            conn.execute(statement)

    def mirror(self, mirror_name: str):
        mirror = self.settings.mirrors[mirror_name]
        source_peer = self.peers[mirror.peers.source]
        destination_peer = self.peers[mirror.peers.destination]
        peer_types = (source_peer.type, destination_peer.type)

        if peer_types == (AdapterType.DUCKDB, AdapterType.POSTGRES):
            mirror_method = "_mirror_duckdb_to_postgres"
        elif peer_types == (AdapterType.POSTGRES, AdapterType.DUCKDB):
            mirror_method = "_mirror_postgres_to_duckdb"
        else:
            raise ValueError(
                f"Peer types must be '{AdapterType.DUCKDB}' and '{AdapterType.POSTGRES}'."
            )

        return getattr(self, mirror_method)(mirror)
