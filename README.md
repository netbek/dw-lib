# dw-lib

Tools for working with Postgres, ClickHouse, and DuckDB.

## Development: Installation

1. Clone the repo and its submodules:

    ```shell
    git clone --recurse-submodules git@github.com:netbek/dw-lib.git
    ```

2. Install [Docker Engine v23 or higher](https://docs.docker.com/engine/install/) and [Docker Compose v2 or higher](https://docs.docker.com/compose/install/). Follow the links for instructions or run this script:

    ```shell
    ./scripts/install.sh docker
    ```

3. Install Nix:

    ```shell
    sh <(curl -L https://nixos.org/nix/install) --daemon
    ```

4. Configure Nix. Edit `/etc/nix/nix.conf` (for a multi-user installation) or `~/.config/nix/nix.conf` (for a single-user installation) to include the following lines:

    ```shell
    experimental-features = nix-command flakes
    trusted-users = root <USER>
    ```

    Replace `<USER>` with your username on your computer.

5. Install direnv:

    ```shell
    sudo apt install direnv
    ```

6. Enable direnv in your shell by adding a line to your shell configuration file.

    For Bash, edit `~/.bashrc`:

    ```shell
    eval "$(direnv hook bash)"
    ```

7. Allow `.envrc`:

    ```shell
    direnv allow
    ```

## License

Copyright (c) 2025 Hein Bekker. Licensed under the GNU Affero General Public License, version 3.
