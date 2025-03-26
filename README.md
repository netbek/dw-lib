# dw

Tools for working with Postgres, ClickHouse, and DuckDB.

## Installation

## Development

| Command                    | Description                                                         |
|----------------------------|---------------------------------------------------------------------|
| `./scripts/run.sh build`   | Build the Docker images.                                            |
| `./scripts/run.sh destroy` | Delete the Docker images, volumes and network.                      |
| `./scripts/run.sh clean`   | Delete temporary files and directories, e.g. `__pycache__`          |
| `./scripts/run.sh up`      | Start the Docker services.                                          |
| `./scripts/run.sh down`    | Stop the Docker services.                                           |
| `./scripts/run.sh shell`   | Start the Docker services and open an interactive shell.            |
| `./scripts/run.sh vscode`  | Start the Docker services and open VS Code.                         |
| `./scripts/run.sh test`    | Start the Docker services and run the unit tests.                   |

## License

Copyright (c) 2025 Hein Bekker. Licensed under the GNU Affero General Public License, version 3.
