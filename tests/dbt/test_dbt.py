from .conftest import CodeGenerationTest
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.dbt import bundle_docs, Dbt, normalize_rows_affected
from dw_lib.dbt.types import DbtResourceType
from dw_lib.types import ClickHouseRelation
from pathlib import Path
from sqlmodel import Table

import pytest


class InvocationTest:
    @pytest.fixture
    def profiles_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / "dbt"

    @pytest.fixture
    def dbt(self, profiles_dir, project_dir) -> Dbt:
        return Dbt(profiles_dir=profiles_dir, project_dir=project_dir)


class TestAttributes(InvocationTest):
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

    def test_models_dir(self, project_dir: Path, dbt: Dbt):
        assert dbt.models_dir == project_dir / "models"


class TestListResources(InvocationTest):
    def test_resource_types_one(self, dbt: Dbt):
        resources = dbt.list_resources(resource_types=[DbtResourceType.SEED])
        resource_names = [resource.name for resource in resources]
        assert resource_names == ["my_first_dbt_seed"]

    def test_resource_types_non_existant(self, dbt: Dbt):
        with pytest.raises(ValueError, match="'resource_types' must be any of: model, seed"):
            dbt.list_resources(resource_types=["non_existant"])

    def test_select_all(self, dbt: Dbt):
        resources = dbt.list_resources()
        resource_names = [resource.name for resource in resources]
        assert resource_names == [
            "my_first_dbt_model",
            "my_first_dbt_seed",
            "my_second_dbt_model",
            "test_table",
        ]

    def test_select_one(self, dbt: Dbt):
        resources = dbt.list_resources(select="my_second_dbt_model")
        resource_names = [resource.name for resource in resources]
        assert resource_names == ["my_second_dbt_model"]

    def test_select_non_existant(self, dbt: Dbt):
        resources = dbt.list_resources(select="non_existant")
        resource_names = [resource.name for resource in resources]
        assert resource_names == []


class TestGenerateModelYAML(InvocationTest, CodeGenerationTest):
    def test_replace(
        self,
        dbt: Dbt,
        clickhouse_adapter: ClickHouseAdapter,
        relation: ClickHouseRelation,
        table: Table,
    ):
        actual = dbt.generate_model_yaml(clickhouse_adapter, merge=False)
        expected_yaml = """
version: 2

models:
  - name: test_table
    columns:
      - name: uint64
        data_type: UInt64
      - name: int64
        data_type: Int64
      - name: uint32
        data_type: UInt32
      - name: int32
        data_type: Int32
      - name: uint16
        data_type: UInt16
      - name: int16
        data_type: Int16
      - name: uint8
        data_type: UInt8
      - name: int8
        data_type: Int8
      - name: decimal256
        data_type: Decimal(76, 1)
      - name: decimal128
        data_type: Decimal(38, 1)
      - name: decimal64
        data_type: Decimal(18, 1)
      - name: decimal32
        data_type: Decimal(9, 1)
      - name: decimal
        data_type: Decimal(10, 0)
      - name: float64
        data_type: Float64
      - name: float32
        data_type: Float32
      - name: bool
        data_type: Bool
      - name: nullable_bool
        data_type: Nullable(Bool)
      - name: date32
        data_type: Date32
      - name: datetime
        data_type: DateTime
      - name: nullable(datetime)
        data_type: Nullable(DateTime)
      - name: datetime64
        data_type: DateTime64(9)
      - name: nullable_datetime64
        data_type: Nullable(DateTime64(9))
      - name: string
        data_type: String
      - name: nullable_string
        data_type: Nullable(String)
      - name: uuid
        data_type: UUID
      - name: nullable_uuid
        data_type: Nullable(UUID)
      - name: _peerdb_synced_at
        data_type: DateTime64(9)
      - name: _peerdb_is_deleted
        data_type: Int8
      - name: _peerdb_version
        data_type: Int64
"""
        assert list(actual.keys()) == ["test_table"]
        assert actual["test_table"].strip() == expected_yaml.strip()

    def test_merge(
        self,
        dbt: Dbt,
        clickhouse_adapter: ClickHouseAdapter,
        relation: ClickHouseRelation,
        table: Table,
    ):
        actual = dbt.generate_model_yaml(clickhouse_adapter, merge=True)
        expected_yaml = """
version: 2

models:
  - name: test_table
    description: Test table
    columns:
      - name: uint64
        description: Short description
        data_type: UInt64
      - name: int64
        data_type: Int64
      - name: uint32
        description: |-
          Description that spans
          Multiple lines in a row,

          Brief thoughts take their shape.
        data_type: UInt32
      - name: int32
        data_type: Int32
      - name: uint16
        data_type: UInt16
      - name: int16
        data_type: Int16
      - name: uint8
        data_type: UInt8
      - name: int8
        data_type: Int8
      - name: decimal256
        data_type: Decimal(76, 1)
      - name: decimal128
        data_type: Decimal(38, 1)
      - name: decimal64
        data_type: Decimal(18, 1)
      - name: decimal32
        data_type: Decimal(9, 1)
      - name: decimal
        data_type: Decimal(10, 0)
      - name: float64
        data_type: Float64
      - name: float32
        data_type: Float32
      - name: bool
        data_type: Bool
      - name: nullable_bool
        data_type: Nullable(Bool)
      - name: date32
        data_type: Date32
      - name: datetime
        data_type: DateTime
      - name: nullable(datetime)
        data_type: Nullable(DateTime)
      - name: datetime64
        data_type: DateTime64(9)
      - name: nullable_datetime64
        data_type: Nullable(DateTime64(9))
      - name: string
        data_type: String
      - name: nullable_string
        data_type: Nullable(String)
      - name: uuid
        data_type: UUID
      - name: nullable_uuid
        data_type: Nullable(UUID)
      - name: _peerdb_synced_at
        data_type: DateTime64(9)
      - name: _peerdb_is_deleted
        data_type: Int8
      - name: _peerdb_version
        data_type: Int64
"""
        assert list(actual.keys()) == ["test_table"]
        assert actual["test_table"].strip() == expected_yaml.strip()


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


class TestBundleDocs:
    def test_bundle_docs(self, pytestconfig):
        project_dir = Path(__file__).parent / "data" / "bundle_docs"
        dest_dir = pytestconfig.rootpath / "tests" / "temp" / "bundle_docs"
        dest_file = bundle_docs(project_dir, dest_dir=dest_dir)

        assert dest_file.is_file() is True
        assert dest_file.exists() is True
