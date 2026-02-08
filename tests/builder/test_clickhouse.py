from ..asserts import assert_sql_equal
from ..conftest import DatabaseTest
from . import clickhouse_models as models
from dw_lib.builder.clickhouse import Graph
from dw_lib.database.adapters import ClickHouseAdapter


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
