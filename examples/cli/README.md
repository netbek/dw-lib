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

| Command | Description |
|---|---|
| `cli peerdb debug` | Check PeerDB configuration, connections, publications, peers, mirrors and replication slots. |
| `cli peerdb up` | Apply settings, create all configured peers and mirrors, and start PeerDB setup. |
| `cli peerdb settings update` | Apply settings from `peerdb.yaml`. |
| `cli peerdb peer create` / `cli peerdb peer drop` | Create or drop one peer or all configured peers. |
| `cli peerdb mirror create` / `cli peerdb mirror drop` | Create or drop one mirror or all mirrors. |
| `cli peerdb mirror pause` / `cli peerdb mirror resume` | Pause or resume one mirror or all mirrors. |
| `cli peerdb mirror resync` | Resync one mirror or all mirrors. |

Append the `--help` option to see the options of each command. See [PeerDB CLI](../../docs/peerdb-cli.md) for command behavior, lifecycle statuses and blocking behavior.

Check the status of peers and mirrors in the [PeerDB UI](http://localhost:3000) after running `cli peerdb up`, or run `cli peerdb debug`. To tear down the example, run `cli peerdb peer drop --all --drop-destination-tables`.

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
