from dw_lib.peerdb import PeerDB
from pathlib import Path
from pydantic import ValidationError

import pytest

ENGINE_VALUES = [
    "CH_ENGINE_REPLACING_MERGE_TREE",
    "CH_ENGINE_MERGE_TREE",
    "CH_ENGINE_NULL",
    "CH_ENGINE_REPLICATED_REPLACING_MERGE_TREE",
    "CH_ENGINE_REPLICATED_MERGE_TREE",
    "CH_ENGINE_COALESCING_MERGE_TREE",
]


def make_peerdb(tmp_path: Path, table_mapping: str) -> PeerDB:
    """Write a PeerDB config with one mirror and return the client."""
    config_file = tmp_path / "peerdb.yaml"
    config_file.write_text(
        "peerdb_ui_url: http://localhost:3000\n"
        "mirrors:\n"
        "  cdc_one:\n"
        "    source_name: source\n"
        "    destination_name: destination\n"
        "    table_mappings:\n"
        f"{table_mapping}"
    )

    return PeerDB(config_file=config_file)


def minimal_table_mapping(extra: str = "") -> str:
    """Return an indented table mapping with optional extra lines."""
    mapping = (
        "      - source_table_identifier: public.table_1\n"
        "        destination_table_identifier: table_1\n"
    )

    return mapping + extra


class TestConfigMirrorTableMapping:
    """Offline tests for mirror table mapping config parsing."""

    def test_full_table_mapping_parses(self, tmp_path: Path):
        """Verify every table mapping option is parsed."""
        peerdb = make_peerdb(
            tmp_path,
            minimal_table_mapping(
                "        partition_key: id\n"
                "        exclude: [password]\n"
                "        engine: CH_ENGINE_REPLICATED_MERGE_TREE\n"
                "        sharding_key: rand()\n"
                "        policy_name: default\n"
                "        partition_by_expr: toYYYYMM(modified_at)\n"
                "        columns:\n"
                "          - source_name: id\n"
                "            destination_name: id\n"
                "            destination_type: UInt64\n"
                "            ordering: 1\n"
                "            partitioning: 1\n"
                "            nullable_enabled: false\n"
            ),
        )
        table_mapping = peerdb.config.mirrors[0].table_mappings[0]

        assert table_mapping.source_table_identifier == "public.table_1"
        assert table_mapping.destination_table_identifier == "table_1"
        assert table_mapping.partition_key == "id"
        assert table_mapping.exclude == ["password"]
        assert table_mapping.engine == "CH_ENGINE_REPLICATED_MERGE_TREE"
        assert table_mapping.sharding_key == "rand()"
        assert table_mapping.policy_name == "default"
        assert table_mapping.partition_by_expr == "toYYYYMM(modified_at)"

        column_setting = table_mapping.columns[0]

        assert column_setting.source_name == "id"
        assert column_setting.destination_name == "id"
        assert column_setting.destination_type == "UInt64"
        assert column_setting.ordering == 1
        assert column_setting.partitioning == 1
        assert column_setting.nullable_enabled is False

    def test_minimal_table_mapping_defaults_to_none(self, tmp_path: Path):
        """Verify table mapping options are unset by default."""
        peerdb = make_peerdb(tmp_path, minimal_table_mapping())
        table_mapping = peerdb.config.mirrors[0].table_mappings[0]

        assert table_mapping.partition_key is None
        assert table_mapping.columns is None
        assert table_mapping.engine is None
        assert table_mapping.sharding_key is None
        assert table_mapping.policy_name is None
        assert table_mapping.partition_by_expr is None

    def test_model_dump_includes_table_mapping_options(self, tmp_path: Path):
        """Verify table mapping options survive model_dump for the API payload."""
        peerdb = make_peerdb(
            tmp_path,
            minimal_table_mapping(
                "        partition_key: id\n"
                "        engine: CH_ENGINE_MERGE_TREE\n"
                "        columns:\n"
                "          - source_name: id\n"
                "            ordering: 1\n"
            ),
        )
        dumped = peerdb.config.mirrors[0].model_dump()
        table_mapping = dumped["table_mappings"][0]

        assert table_mapping["partition_key"] == "id"
        assert table_mapping["engine"] == "CH_ENGINE_MERGE_TREE"
        assert table_mapping["columns"] == [
            {
                "source_name": "id",
                "destination_name": None,
                "destination_type": None,
                "ordering": 1,
                "partitioning": None,
                "nullable_enabled": None,
            }
        ]

    @pytest.mark.parametrize("engine", ENGINE_VALUES)
    def test_every_engine_value_accepted(self, tmp_path: Path, engine: str):
        """Verify all backend engine values are accepted."""
        peerdb = make_peerdb(tmp_path, minimal_table_mapping(f"        engine: {engine}\n"))
        table_mapping = peerdb.config.mirrors[0].table_mappings[0]

        assert table_mapping.engine == engine

    def test_unknown_engine_rejected(self, tmp_path: Path):
        """Verify an engine value the backend does not define is rejected."""
        peerdb = make_peerdb(tmp_path, minimal_table_mapping("        engine: CH_ENGINE_UNKNOWN\n"))

        with pytest.raises(ValidationError):
            peerdb.config  # noqa: B018

    def test_column_setting_requires_source_name(self, tmp_path: Path):
        """Verify a column setting without source_name is rejected."""
        peerdb = make_peerdb(
            tmp_path,
            minimal_table_mapping(
                "        columns:\n          - destination_name: id\n",
            ),
        )

        with pytest.raises(ValidationError):
            peerdb.config  # noqa: B018
