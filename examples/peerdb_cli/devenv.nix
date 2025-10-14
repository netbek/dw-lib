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
    if [ -d "${config.env.DEVENV_STATE}/venv" ]; then
      ln -sfn ${config.env.DEVENV_STATE}/venv venv
    else
      echo "${config.env.DEVENV_STATE}/venv not found"
      exit 1
    fi
  '';
}
