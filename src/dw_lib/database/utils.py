from jinja2 import Environment, StrictUndefined
from sqlglot import exp
from sqlglot.dialects.dialect import DialectType
from typing import Any

import re
import sqlparse

RE_HAS_JINJA = re.compile(r"({[{%#]|[#}%]})")

jinja_env = Environment(
    extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"], undefined=StrictUndefined
)


def quote_identifier(identifier: str, dialect: DialectType) -> str:
    return exp.Identifier(this=identifier, quoted=True).sql(dialect=dialect)


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
