# CLI example

## Setup

1. Trust `mise.toml`:

    ```shell
    mise trust
    ```

2. Start the Docker services:

    ```shell
    docker compose up
    ```

3. Install the dbt dependencies:

    ```shell
    cd dbt
    dbt deps
    ```

## Databases

The connection settings of the database servers in this example are:

| Server         | Host        | Port    | Username   | Password   | Database   |
|----------------|-------------|---------|------------|------------|------------|
| Postgres       | `localhost` | `25432` | `postgres` | `postgres` | `test`     |
| ClickHouse     | `localhost` | `28123` | `default`  | `default`  | `test`     |

## PeerDB

### CLI PeerDB commands

| Command                                           | Description                                                                                                                 |
|---------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| `cli peerdb debug`                                | Check the PeerDB configuration and connections.                                                                             |
| `cli peerdb up`                                   | Add PeerDB publications and replication slots to the source database.                                                       |
| `cli peerdb drop-peers --drop-destination-tables` | Remove PeerDB publications and replication slots from the source database, and remove tables from the destination database. |

Append the `--help` option to see the options of each command.

### Serial and parallel mirror processing

By default, `cli peerdb up`, `cli peerdb mirror create`, and `cli peerdb mirror resync` wait for each mirror to become ready before starting the next. This keeps initial snapshots and resyncs from running concurrently.

Pass `--parallel` to start each mirror operation as soon as PeerDB accepts it:

```shell
cli peerdb up --parallel
cli peerdb mirror create --all --parallel
cli peerdb mirror resync --all --parallel
```

Both modes apply to the whole run, not per source. The readiness wait has no timeout and stops at the first failed, terminated, or terminating mirror. A resync start is bounded to 15 minutes by default; if PeerDB does not begin the resync in that time, the command fails. Transient status-query errors are retried, and serial waits report status changes and periodic heartbeats. Resyncing a completed or failed mirror recreates it; serial mode waits for the recreated mirror to become ready. Kept mirrors (`if_exists=keep`) are not waited on. Mirror drops are already processed one at a time, waiting up to `operation_timeout`, and have no `--parallel` option.

### Wait settings

The YAML config can override the default wait behaviour:

| Key | Default | Meaning |
|-----|---------|---------|
| `resync_start_timeout` | `900` | Seconds to wait for a resync to start. |
| `status_poll_interval` | `1` | Initial status poll interval; fixed interval for the resync-start wait. |
| `status_poll_max_interval` | `15` | Maximum backoff interval for the readiness wait. |
| `status_error_window` | `600` | Seconds of consecutive status-query failures before aborting. |
| `status_heartbeat_interval` | `300` | Seconds between progress heartbeats. |
| `status_unknown_grace` | `60` | Seconds before `STATUS_UNKNOWN` is treated as failed in the readiness wait. |

`status_poll_max_interval` must be greater than or equal to `status_poll_interval`. The resync-start wait uses `status_poll_interval` as a fixed interval; the default of 1 second is recommended.

Check the status of peers and mirrors in the [PeerDB UI](http://localhost:3000) after running `cli peerdb up` and `cli peerdb drop-peers`.

## dbt

Note that dbt and CLI commands must be run in the dbt project directory `dbt`.

### dbt commands

[Refer to the dbt documentation for available commands](https://docs.getdbt.com/reference/dbt-commands).

### CLI dbt commands

| Command                       | Description                                                                                                                 |
|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| `cli dbt version`             | Print dbt version.                                                                                                          |
| `cli dbt model-yaml`          | Generate the model schema YAML, e.g. `cli dbt model-yaml my_first_dbt_model`                                                |
| `cli dbt docs generate`       | Generate the project docs.                                                                                                  |
| `cli dbt docs serve`          | Serve the project docs.                                                                                                     |

Append the `--help` option to see the options of each command.

## Teardown

1. Stop the Docker services:

    ```shell
    docker compose down -v
    ```
