from ..asserts import assert_sql_equal
from ..conftest import DatabaseTest
from . import clickhouse_models as models
from dw_lib.builder.clickhouse import Graph
from dw_lib.database.adapters import ClickHouseAdapter
from pydantic import ValidationError

import pytest


class TestBaseTable(DatabaseTest):
    def test_make_create_statement_external_materialization(
        self, clickhouse_adapter: ClickHouseAdapter
    ):
        assert models.RawMeasurement.make_create_statement(clickhouse_adapter) is None

    def test_make_create_statement_local_materialization(
        self, clickhouse_adapter: ClickHouseAdapter
    ):
        actual = models.Measurement.make_create_statement(clickhouse_adapter)
        expected = """
        CREATE TABLE analytics.measurement (
            device_id Int32,
            timestamp DateTime64(6),
            temperature Nullable(Decimal(NONE, NONE))
        )
        ENGINE=MergeTree()
        ORDER BY (device_id, timestamp)
        """
        assert_sql_equal(actual, expected)


class TestBaseView(DatabaseTest):
    def test_make_create_statement(self, clickhouse_adapter: ClickHouseAdapter):
        actual = models.AggregatedMeasurement.make_create_statement(clickhouse_adapter)
        expected = """
        CREATE VIEW analytics.aggregated_measurement AS
        SELECT
            m.device_id AS device_id,
            m.temperature AS temperature
        FROM analytics.measurement AS m
        INNER JOIN analytics.device AS d
            ON d.id = m.device_id
        """
        assert_sql_equal(actual, expected)


class TestGraph(DatabaseTest):
    def test_select_all_models(self):
        graph = Graph(module=models)
        assert graph.models == (
            models.analytics.device.Device,
            models.dw.model_run.ModelRun,
            models.raw.raw_measurement.RawMeasurement,
            models.analytics.clean_measurement.CleanMeasurement,
            models.analytics.measurement.Measurement,
            models.analytics.aggregated_measurement.AggregatedMeasurement,
        )

    def test_select_given_models_only(self):
        graph = Graph(module=models, select=["Device", "Measurement"])
        assert graph.models == (
            models.analytics.device.Device,
            models.analytics.measurement.Measurement,
        )

    def test_select_given_model_and_ancestors(self):
        graph = Graph(module=models, select=["+AggregatedMeasurement"])
        assert graph.models == (
            models.analytics.device.Device,
            models.raw.raw_measurement.RawMeasurement,
            models.analytics.measurement.Measurement,
            models.analytics.aggregated_measurement.AggregatedMeasurement,
        )

    def test_select_given_model_and_descendants(self):
        graph = Graph(module=models, select=["RawMeasurement+"])
        assert graph.models == (
            models.raw.raw_measurement.RawMeasurement,
            models.analytics.clean_measurement.CleanMeasurement,
            models.analytics.measurement.Measurement,
            models.analytics.aggregated_measurement.AggregatedMeasurement,
        )

    def test_select_given_model_and_ancestors_and_descendants(self):
        graph = Graph(module=models, select=["+Measurement+"])
        assert graph.models == (
            models.raw.raw_measurement.RawMeasurement,
            models.analytics.measurement.Measurement,
            models.analytics.aggregated_measurement.AggregatedMeasurement,
        )

    def test_select_is_not_list(self):
        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select="Measurement")
        assert (
            "Input should be a valid list [type=list_type, input_value='Measurement', input_type=str]"
            in str(exc.value)
        )

    def test_select_item_is_not_string(self):
        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select=[None])
        assert (
            "Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]"
            in str(exc.value)
        )

    def test_select_item_is_malformed(self):
        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select=[""])
        assert (
            "Value error, Invalid select ''. Expected formats: Model, +Model, Model+, +Model+ [type=value_error, input_value=[''], input_type=list]"
            in str(exc.value)
        )

        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select=["+"])
        assert (
            "Value error, Invalid select '+'. Expected formats: Model, +Model, Model+, +Model+ [type=value_error, input_value=['+'], input_type=list]"
            in str(exc.value)
        )

        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select=["++Measurement"])
        assert (
            "Value error, Invalid select '++Measurement'. Expected formats: Model, +Model, Model+, +Model+ [type=value_error, input_value=['++Measurement'], input_type=list]"
            in str(exc.value)
        )

        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select=["Measurement++"])
        assert (
            "Value error, Invalid select 'Measurement++'. Expected formats: Model, +Model, Model+, +Model+ [type=value_error, input_value=['Measurement++'], input_type=list]"
            in str(exc.value)
        )

        with pytest.raises(ValidationError) as exc:
            Graph(module=models, select=["++Measurement++"])
        assert (
            "Value error, Invalid select '++Measurement++'. Expected formats: Model, +Model, Model+, +Model+ [type=value_error, input_value=['++Measurement++'], input_type=list]"
            in str(exc.value)
        )
