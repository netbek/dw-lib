from jinja2 import Environment, FileSystemLoader, Undefined
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Type


class EnvVars(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=list(Path("/usr/local/share/dw").glob("*.env")),
        extra="allow",
        case_sensitive=True,
    )


def env_var(var: str, default: Optional[str] = None) -> str:
    return getattr(EnvVars(), var, default)


def render_template(
    file_path: str, context: Optional[dict] = None, undefined: Type[Undefined] = Undefined
) -> str:
    env = Environment(loader=FileSystemLoader("/"), undefined=undefined)
    env.globals["env_var"] = env_var
    template = env.get_template(str(file_path))

    return template.render(context or {})
