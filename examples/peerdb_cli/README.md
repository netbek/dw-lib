# Example

Example of CLI for PeerDB.

## Setup

1. Allow `.envrc`:

    ```shell
    direnv allow
    ```

2. Start the Docker containers:

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

Check the status of peers and mirrors in the [PeerDB UI](http://localhost:3000) after running `peerdb up` and `peerdb down`.

## Teardown

1. Stop the Docker containers:

    ```shell
    docker compose down -v
    ```
