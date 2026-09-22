# dw-lib

Tools for working with Postgres, ClickHouse, and DuckDB.

## Development

### Prerequisites

1. Clone the repo:

    ```shell
    git clone git@github.com:netbek/dw-lib.git
    ```

2. Install [Docker Engine v23 or higher](https://docs.docker.com/engine/install/) and [Docker Compose v2 or higher](https://docs.docker.com/compose/install/). Follow the links for instructions or run this script:

    ```shell
    ./scripts/install.sh docker
    ```

3. Install Mise and add activation to `~/.bashrc`, e.g.

    ```shell
    curl -fsSL https://github.com/jdx/mise/releases/download/v2026.7.13/install.sh | sh
    ```

    See [other installation methods](https://mise.en.dev/installing-mise.html).

4. Trust `mise.toml`:

    ```shell
    mise trust
    ```

5. Create a [PyPI API token](https://pypi.org/manage/account/#api-tokens), and add the token to the system keyring as the password:

    ```shell
    keyring set pypi-dw-lib __token__
    ```

### Release

Build and publish the Python distribution package:

1. Run `make bump-version [major|minor|patch]`. This bumps `pyproject.toml` and `package.json`, then commits.
2. Push the commit.
3. Run `make build`. This builds the distribution package.
4. Check the tree is clean, then run `make create-release`.
5. Run `make publish`. This publishes the distribution package.

## License

Copyright (c) 2025 Hein Bekker. Licensed under the GNU Affero General Public License, version 3.
