from dw_lib.utils.template import render_template
from jinja2 import DebugUndefined


class TestRenderTemplate:
    def test_undefined(self):
        actual = render_template(
            "/app/tests/utils/template/fixtures/template.md",
            context={"a": "Jane"},
        )
        assert actual == "Jane says "

        actual = render_template(
            "/app/tests/utils/template/fixtures/template.md",
            context={"a": "Jane"},
            undefined=DebugUndefined,
        )
        assert actual == "Jane says {{ b }}"
