from dw_lib.dbt import bundle_docs
from pathlib import Path


class TestBundleDocs:
    def test_bundle_docs(self, pytestconfig):
        project_dir = Path(__file__).parent / "data" / "bundle_docs"
        dest_dir = pytestconfig.rootpath / "tests" / "temp" / "bundle_docs"
        dest_file = bundle_docs(project_dir, dest_dir=dest_dir)

        assert dest_file.is_file() is True
        assert dest_file.exists() is True
