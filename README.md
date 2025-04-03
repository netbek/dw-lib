# dw-lib

Tools for working with Postgres, ClickHouse, and DuckDB.

## Install

## Development

1. Clone the repo and its submodules:

    ```shell
    git clone --recurse-submodules https://github.com/netbek/dw-lib.git
    ```

2. Install [Docker Engine v23 or higher](https://docs.docker.com/engine/install/) and [Docker Compose v2 or higher](https://docs.docker.com/compose/install/). Follow the links for instructions or run this script:

    ```shell
    ./scripts/install.sh docker
    ```

3. Install [uv v0.6.12 or higher](https://docs.astral.sh/uv/getting-started/installation/). Follow the links for instructions or run this script:

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

6. Build the Docker image:

    ```shell
    ./scripts/run.sh build
    ```

| Command                    | Description                                                         |
|----------------------------|---------------------------------------------------------------------|
| `./scripts/run.sh build`   | Build the Docker image.                                             |
| `./scripts/run.sh destroy` | Delete the Docker image and network.                                |
| `./scripts/run.sh clean`   | Delete temporary files and directories, e.g. `__pycache__`          |
| `./scripts/run.sh up`      | Start the Docker services.                                          |
| `./scripts/run.sh down`    | Stop the Docker services.                                           |
| `./scripts/run.sh shell`   | Start the Docker services and open an interactive shell.            |
| `./scripts/run.sh vscode`  | Start the Docker services and open VS Code.                         |
| `./scripts/run.sh test`    | Start the Docker services and run the unit tests.                   |

## License

Copyright (c) 2025 Hein Bekker. Licensed under the GNU Affero General Public License, version 3.
