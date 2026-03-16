from jinja2 import Environment, FileSystemLoader, Undefined
from pathlib import Path

import os


def env_var(var: str, default: str | None = None) -> str | None:
    return os.environ.get(var, default=default)


def render_template(
    file: Path | str, context: dict | None = None, undefined: type[Undefined] = Undefined
) -> str:
    env = Environment(
        loader=FileSystemLoader("/"),
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
        undefined=undefined,
    )
    env.globals["env_var"] = env_var
    template = env.get_template(str(file))

    return template.render(context or {})
