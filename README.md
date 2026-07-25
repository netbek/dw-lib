# dw-lib

Tools for working with Postgres, ClickHouse, and DuckDB.

## Development: Installation

1. Clone the repo:

    ```shell
    git clone git@github.com:netbek/dw-lib.git
    ```

2. Install [Docker Engine v23 or higher](https://docs.docker.com/engine/install/) and [Docker Compose v2 or higher](https://docs.docker.com/compose/install/). Follow the links for instructions or run this script:

    ```shell
    ./scripts/install.sh docker
    ```

3. Install Mise, e.g.

    ```shell
    curl https://mise.run/bash | sh
    ```

    See [other installation methods](https://mise.en.dev/installing-mise.html).

4. Enable Mise in your shell by adding a line to your shell configuration file.

    For Bash, edit `~/.bashrc`:

    ```shell
    eval "$(mise activate bash)"
    ```

5. Trust `mise.toml`:

    ```shell
    mise trust
    ```

6. Create a [PyPI API token](https://pypi.org/manage/account/#api-tokens), and add the token to the system keyring as the password:

    ```shell
    keyring set pypi-dw-lib __token__
    ```

## Development: Usage

Build and publish the Python distribution package:

```shell
make bump-version [major|minor|patch]
git push
make build
make create-release
make publish
```

## License

Copyright (c) 2025 Hein Bekker. Licensed under the GNU Affero General Public License, version 3.
