{
  pkgs,
  lib,
  config,
  inputs,
  ...
}:
{
  env.DEVENV_TASKS_QUIET = 1;

  packages = with pkgs; [
    nixfmt-rfc-style
    pre-commit
    ripgrep
  ];

  languages = {
    python = {
      enable = true;
      uv = {
        enable = true;
        sync = {
          enable = true;
          allGroups = true;
        };
      };
    };
  };

  # For an unknown reason, after running `cd examples/cli/packages/example_cli && uv sync`,
  # the current pytest is the one in the Nix store, not the virtual environment. As a workaround,
  # run `uv sync` again in the root.
  scripts.uv_sync_all.exec = ''
    cd "$DEVENV_ROOT" && uv sync --all-groups
    cd "$DEVENV_ROOT/examples/cli" && uv sync --all-groups
    cd "$DEVENV_ROOT/examples/cli/packages/example_cli" && uv sync --all-groups
    cd "$DEVENV_ROOT" && uv sync --all-groups
  '';

  scripts.uv_lock_upgrade_all.exec = ''
    cd "$DEVENV_ROOT" && uv lock --upgrade
    cd "$DEVENV_ROOT/examples/cli" && uv lock --upgrade
    cd "$DEVENV_ROOT/examples/cli/packages/example_cli" && uv lock --upgrade
  '';

  enterShell = ''
    VENV_PATH="${config.env.DEVENV_STATE}/venv"

    if [ -d "$VENV_PATH" ]; then
      ln -sfn "$VENV_PATH" venv
      source "$VENV_PATH/bin/activate"
    else
      echo "$VENV_PATH not found"
      exit 1
    fi

    if [ -d ".git" ]; then
      pre-commit install --overwrite > /dev/null 2>&1
    fi
  '';
}
