from jinja2 import Environment, StrictUndefined
from typing import Any

import re
import sqlparse

RE_HAS_JINJA = re.compile(r"({[{%#]|[#}%]})")

jinja_env = Environment(
    extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"], undefined=StrictUndefined
)


def render_statement(
    statement: str, context: dict[str, Any] | None = None, pretty: bool = False
) -> str:
    if RE_HAS_JINJA.search(statement):
        statement = jinja_env.from_string(statement, context).render()

    statement = statement.strip()

    if pretty:
        statement = sqlparse.format(
            statement, reindent=True, keyword_case="lower", identifier_case="lower"
        )

    return statement
