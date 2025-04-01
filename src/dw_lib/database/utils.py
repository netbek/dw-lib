from jinja2 import Environment, StrictUndefined
from typing import Any, Optional

import re
import sqlparse

RE_HAS_JINJA = re.compile(r"({[{%#]|[#}%]})")

jinja_env = Environment(
    extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"], undefined=StrictUndefined
)


def escape_sql_value(value):
    if isinstance(value, str):
        return value.replace("'", "''")
    return value


def render_statement(
    statement: str, context: Optional[dict[str, Any]] = None, pretty: bool = False
) -> str:
    if RE_HAS_JINJA.search(statement):
        statement = jinja_env.from_string(statement, context).render()

    statement = statement.strip()

    if pretty:
        statement = sqlparse.format(
            statement, reindent=True, keyword_case="lower", identifier_case="lower"
        )

    return statement
