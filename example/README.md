# Example

Example of CLI for PeerDB.

## Setup

Start the Docker containers:

```shell
docker compose up
```

## CLI commands

| Command                       | Description                                                                                                                 |
|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| `peerdb debug`                | Check the PeerDB configuration and connections.                                                                             |
| `peerdb up`                   | Add PeerDB publications and replication slots to the source database.                                                       |
| `peerdb down`                 | Remove PeerDB publications and replication slots from the source database, and remove tables from the destination database. |

Append the `--help` option to see the options of each command.

## Teardown

Stop the Docker containers:

```shell
docker compose down -v
```
