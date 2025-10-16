{
  pkgs,
  lib,
  config,
  inputs,
  ...
}:
{
  env.DEVENV_TASKS_QUIET = 1;
  env.DBT_PROFILES_DIR = "${config.env.DEVENV_ROOT}/.dbt";

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

  enterShell = ''
    VENV_PATH="${config.env.DEVENV_STATE}/venv"

    if [ -d "$VENV_PATH" ]; then
      ln -sfn "$VENV_PATH" venv
      source "$VENV_PATH/bin/activate"
    else
      echo "$VENV_PATH not found"
      exit 1
    fi
  '';
}
