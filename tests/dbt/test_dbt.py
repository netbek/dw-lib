from dw_lib.dbt import bundle_docs, normalize_rows_affected
from pathlib import Path


class TestBundleDocs:
    def test_bundle_docs(self, pytestconfig):
        project_dir = Path(__file__).parent / "data" / "bundle_docs"
        dest_dir = pytestconfig.rootpath / "tests" / "temp" / "bundle_docs"
        dest_file = bundle_docs(project_dir, dest_dir=dest_dir)

        assert dest_file.is_file() is True
        assert dest_file.exists() is True


class TestNormalizeRowsAffected:
    def test_literal(self):
        assert normalize_rows_affected(None) is None
        assert normalize_rows_affected(-1) is None
        assert normalize_rows_affected(-100) is None
        assert normalize_rows_affected(0) == 0
        assert normalize_rows_affected(1) == 1
        assert normalize_rows_affected(100) == 100

    def test_string(self):
        assert normalize_rows_affected("") is None
        assert normalize_rows_affected("-1") is None
        assert normalize_rows_affected("-100") is None
        assert normalize_rows_affected("0") == 0
        assert normalize_rows_affected("1") == 1
        assert normalize_rows_affected("100") == 100
