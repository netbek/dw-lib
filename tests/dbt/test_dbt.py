from dw_lib.dbt import bundle_docs, Dbt, normalize_rows_affected
from pathlib import Path

import pytest


class TestAttributes:
    @pytest.fixture
    def profiles_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / "dbt"

    @pytest.fixture
    def dbt(self, profiles_dir, project_dir) -> Dbt:
        return Dbt(profiles_dir=profiles_dir, project_dir=project_dir)

    def test_profiles_file(self, profiles_dir: Path, dbt: Dbt):
        assert dbt.profiles_file == profiles_dir / "profiles.yml"

    def test_project_config_file(self, project_dir: Path, dbt: Dbt):
        assert dbt.project_config_file == project_dir / "dbt_project.yml"

    def test_project_config(self, dbt: Dbt):
        assert dbt.project_config == {
            "name": "example",
            "version": "1.0.0",
            "profile": "example",
            "model-paths": ["models"],
            "analysis-paths": ["analyses"],
            "test-paths": ["tests"],
            "seed-paths": ["seeds"],
            "macro-paths": ["macros"],
            "snapshot-paths": ["snapshots"],
            "clean-targets": ["logs", "target", "dbt_packages"],
            "flags": {
                "fail_fast": True,
                "partial_parse": True,
                "send_anonymous_usage_stats": False,
                "use_colors": True,
            },
            "models": {"example": {"example": {"+materialized": "view"}}},
        }

    def test_docs_dir(self, project_dir: Path, dbt: Dbt):
        assert dbt.docs_dir == project_dir / "docs"


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
