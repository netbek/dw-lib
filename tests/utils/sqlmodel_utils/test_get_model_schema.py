from .conftest import TableWithoutSchema, TableWithSchema, ViewWithoutSchema, ViewWithSchema
from dw_lib.utils.sqlmodel_utils import get_model_schema


class TestGetModelSchema:
    def test_table_without_schema(self):
        assert get_model_schema(TableWithoutSchema) is None

    def test_table_with_schema(self):
        assert get_model_schema(TableWithSchema) == "analytics"

    def test_view_without_schema(self):
        assert get_model_schema(ViewWithoutSchema) is None

    def test_view_with_schema(self):
        assert get_model_schema(ViewWithSchema) == "analytics"
