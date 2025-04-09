# dw-lib

Tools for working with Postgres, ClickHouse, and DuckDB.

## Install

## Development

1. Clone the repo and its submodules:

    ```shell
    git clone --recurse-submodules git@github.com:netbek/dw-lib.git
    ```

2. Install [Docker Engine v23 or higher](https://docs.docker.com/engine/install/) and [Docker Compose v2 or higher](https://docs.docker.com/compose/install/). Follow the links for instructions or run this script:

    ```shell
    ./scripts/install.sh docker
    ```

3. Install [uv v0.6.13 or higher](https://docs.astral.sh/uv/getting-started/installation/). Follow the link for instructions or run this script:

    ```shell
    ./scripts/install.sh uv
    ```

4. Install pre-commit:

    ```shell
    ./scripts/install.sh precommit
    ```

5. Install pre-commit hook:

    ```shell
    ./scripts/install.sh precommit_hook
    ```

| Command                    | Description                                                         |
|----------------------------|---------------------------------------------------------------------|
| `./scripts/run.sh clean`   | Delete temporary files and directories, e.g. `__pycache__`          |
| `./scripts/run.sh test`    | Run the unit tests.                                                 |

## License

Copyright (c) 2025 Hein Bekker. Licensed under the GNU Affero General Public License, version 3.
