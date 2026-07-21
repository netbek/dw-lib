{
  pkgs,
  lib,
  config,
  inputs,
  ...
}:
{
  env.DEVENV_TASKS_QUIET = 1;

  languages = {
    python = {
      enable = true;
      package = pkgs.python313;
      uv = {
        enable = true;
        sync = {
          enable = true;
          allGroups = true;
        };
      };
      venv = {
        enable = true;
      };
    };
  };

  enterShell = ''
    VENV_PATH="${config.env.DEVENV_STATE}/venv"

    if [ -d "$VENV_PATH" ]; then
      ln -sfn "$VENV_PATH" venv
    else
      echo "$VENV_PATH not found"
      exit 1
    fi
  '';
}
