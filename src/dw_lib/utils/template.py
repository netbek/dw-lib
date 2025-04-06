from jinja2 import Environment, FileSystemLoader, Undefined
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvVars(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=list(Path("/usr/local/share/dw").glob("*.env")),
        extra="allow",
        case_sensitive=True,
    )


def env_var(var: str, default: str | None = None) -> str:
    return getattr(EnvVars(), var, default)


def render_template(
    file_path: str, context: dict | None = None, undefined: type[Undefined] = Undefined
) -> str:
    env = Environment(
        loader=FileSystemLoader("/"),
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
        undefined=undefined,
    )
    env.globals["env_var"] = env_var
    template = env.get_template(str(file_path))

    return template.render(context or {})
