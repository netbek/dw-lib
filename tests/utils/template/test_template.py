from dw_lib.utils.template import render_template
from jinja2 import DebugUndefined
from pathlib import Path


class TestRenderTemplate:
    def test_undefined(self):
        file = Path(__file__).parent / "data" / "template.md"
        actual = render_template(file, context={"a": "Jane"})
        assert actual == "Jane says "
        actual = render_template(file, context={"a": "Jane"}, undefined=DebugUndefined)
        assert actual == "Jane says {{ b }}"
