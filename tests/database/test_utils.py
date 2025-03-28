from dw_lib.database.utils import render_statement
from jinja2.exceptions import UndefinedError

import pytest


class TestRenderStatement:
    def test_has_context(self):
        query = """
        SELECT {{ columns|join(', ') }}
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        actual = render_statement(query, context={"columns": ["p.name", "c.name"]})
        expected = """
        SELECT p.name, c.name
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """.strip()
        assert actual == expected

    def test_has_undefined_context(self):
        query = """
        SELECT {{ columns|join(', ') }}
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        with pytest.raises(UndefinedError):
            render_statement(query)

    def test_pretty(self):
        query = """
        SELECT *
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        actual = render_statement(query, pretty=False)
        expected = query.strip()
        assert actual == expected

        query = """
        SELECT *
        FROM persons AS p
        JOIN countries AS c ON c.id = p.country_id
        """
        actual = render_statement(query, pretty=True)
        expected = """
select *
from persons as p
join countries as c on c.id = p.country_id
""".strip()
        assert actual == expected
