from dw_lib.utils.template import render_template
from jinja2 import DebugUndefined

import os


class TestRenderTemplate:
    def test_undefined(self, pytestconfig):
        actual = render_template(
            os.path.join(
                pytestconfig.rootpath, "tests/integration/utils/template/fixtures/template.md"
            ),
            context={"a": "Jane"},
        )
        assert actual == "Jane says "

        actual = render_template(
            os.path.join(
                pytestconfig.rootpath, "tests/integration/utils/template/fixtures/template.md"
            ),
            context={"a": "Jane"},
            undefined=DebugUndefined,
        )
        assert actual == "Jane says {{ b }}"
