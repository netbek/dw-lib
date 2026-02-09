from ..asserts import assert_equal_ignoring_whitespace, assert_sql_equal
from ..conftest import DatabaseTest
from . import clickhouse_models as models
from .clickhouse_models import CleanMeasurement, Device
from dw_lib.builder.clickhouse import Graph, Materialization, Runner
from dw_lib.database.adapters import ClickHouseAdapter
from pydantic import ValidationError

import logging
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
        CREATE TABLE staging.measurement (
            device_id Int32 COMMENT 'Unique identifier of device.',
            timestamp DateTime64(6),
            temperature Nullable(Decimal(NONE, NONE)) COMMENT 'Ambient temperature in Celsius.'
        )
        ENGINE=MergeTree()
        ORDER BY (device_id, timestamp)
        """
        assert_sql_equal(actual, expected)


class TestBaseView(DatabaseTest):
    def test_make_create_statement(self, clickhouse_adapter: ClickHouseAdapter):
        actual = models.DeviceMeasurement.make_create_statement(clickhouse_adapter)
        expected = r"""
        CREATE VIEW staging.device_measurement AS
        SELECT
            m.device_id AS device_id,
            m.temperature AS temperature
        FROM staging.measurement AS m
        INNER JOIN staging.device AS d
            ON d.id = m.device_id
        WHERE
            m.id = {device_id: Int32}
        """
        assert_sql_equal(actual, expected)


class TestGraph(DatabaseTest):
    def test_select_all_models(self):
        graph = Graph(module=models)
        assert graph.models == (
            models.raw.raw_measurement.RawMeasurement,
            models.staging.clean_measurement.CleanMeasurement,
            models.staging.device.Device,
            models.staging.measurement.Measurement,
            models.staging.device_measurement.DeviceMeasurement,
        )

    def test_select_given_models_only(self):
        graph = Graph(module=models, select=["Device", "Measurement"])
        assert graph.models == (
            models.staging.device.Device,
            models.staging.measurement.Measurement,
        )

    def test_select_given_model_and_ancestors(self):
        graph = Graph(module=models, select=["+DeviceMeasurement"])
        assert graph.models == (
            models.raw.raw_measurement.RawMeasurement,
            models.staging.device.Device,
            models.staging.measurement.Measurement,
            models.staging.device_measurement.DeviceMeasurement,
        )

    def test_select_given_model_and_descendants(self):
        graph = Graph(module=models, select=["RawMeasurement+"])
        assert graph.models == (
            models.raw.raw_measurement.RawMeasurement,
            models.staging.clean_measurement.CleanMeasurement,
            models.staging.measurement.Measurement,
            models.staging.device_measurement.DeviceMeasurement,
        )

    def test_select_given_model_and_ancestors_and_descendants(self):
        graph = Graph(module=models, select=["+Measurement+"])
        assert graph.models == (
            models.raw.raw_measurement.RawMeasurement,
            models.staging.measurement.Measurement,
            models.staging.device_measurement.DeviceMeasurement,
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

    def test_render_markdown(self):
        graph = Graph(module=models)
        actual = graph.render_markdown()
        expected = """
        ```mermaid
        ---
        config:
          layout: dagre
          look: neo
          theme: neutral
        ---
        graph LR
        A(Device)
        B(DeviceMeasurement)
        C(Measurement)
        D(CleanMeasurement)
        E(RawMeasurement)
        A --> B
        C --> B
        E --> C
        E --> D
        ```
        """
        assert_equal_ignoring_whitespace(actual, expected)


def join_sql_statements(statements: list[str]) -> str:
    return "\n\n".join([statement.strip() + ";" for statement in statements])


class TestRunner(DatabaseTest):
    def test_table_create_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Device, "__materialization__", Materialization.CREATE)

        graph = Graph(module=models, select=["Device"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 4
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'Device'" in caplog.records[1].message
        assert "Finished running model 'Device'" in caplog.records[2].message
        assert "Finished run" in caplog.records[3].message

    def test_table_create_replace_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Device, "__materialization__", Materialization.CREATE_REPLACE)

        graph = Graph(module=models, select=["Device"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        DROP TABLE IF EXISTS staging.device__tmp;

        CREATE TABLE staging.device__tmp AS staging.device;

        INSERT INTO staging.device__tmp (
            SELECT
                42 AS id
        );

        EXCHANGE TABLES staging.device AND staging.device__tmp;

        DROP TABLE staging.device__tmp;

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 4
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'Device'" in caplog.records[1].message
        assert "Finished running model 'Device'" in caplog.records[2].message
        assert "Finished run" in caplog.records[3].message

    def test_table_append_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Device, "__materialization__", Materialization.APPEND)

        graph = Graph(module=models, select=["Device"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 5
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'Device'" in caplog.records[1].message
        assert "Materialization 'append' is not implemented for tables" in caplog.records[2].message
        assert "Finished running model 'Device'" in caplog.records[3].message
        assert "Finished run" in caplog.records[4].message

    def test_table_delete_insert_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Device, "__materialization__", Materialization.DELETE_INSERT)

        graph = Graph(module=models, select=["Device"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        DROP TABLE IF EXISTS staging.device__tmp;

        CREATE TABLE staging.device__tmp AS staging.device;

        INSERT INTO staging.device__tmp (
            SELECT
                42 AS id
        );

        DELETE FROM staging.device
        WHERE device_id IN (
            SELECT device_id
            FROM staging.device__tmp
        );

        INSERT INTO staging.device
            SELECT *
            FROM staging.device__tmp;

        DROP TABLE staging.device__tmp;

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 4
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'Device'" in caplog.records[1].message
        assert "Finished running model 'Device'" in caplog.records[2].message
        assert "Finished run" in caplog.records[3].message

    def test_table_external_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Device, "__materialization__", Materialization.EXTERNAL)

        graph = Graph(module=models, select=["Device"])
        assert Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True) == []

        assert len(caplog.records) == 2
        assert "Started run" in caplog.records[0].message
        assert "Finished run" in caplog.records[1].message

    def test_view_create_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(CleanMeasurement, "__materialization__", Materialization.CREATE)

        graph = Graph(module=models, select=["CleanMeasurement"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 4
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'CleanMeasurement'" in caplog.records[1].message
        assert "Finished running model 'CleanMeasurement'" in caplog.records[2].message
        assert "Finished run" in caplog.records[3].message

    def test_view_create_replace_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(CleanMeasurement, "__materialization__", Materialization.CREATE_REPLACE)

        graph = Graph(module=models, select=["CleanMeasurement"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 4
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'CleanMeasurement'" in caplog.records[1].message
        assert "Finished running model 'CleanMeasurement'" in caplog.records[2].message
        assert "Finished run" in caplog.records[3].message

    def test_view_append_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(CleanMeasurement, "__materialization__", Materialization.APPEND)

        graph = Graph(module=models, select=["CleanMeasurement"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 5
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'CleanMeasurement'" in caplog.records[1].message
        assert "Materialization 'append' is not implemented for views" in caplog.records[2].message
        assert "Finished running model 'CleanMeasurement'" in caplog.records[3].message
        assert "Finished run" in caplog.records[4].message

    def test_view_delete_insert_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(CleanMeasurement, "__materialization__", Materialization.DELETE_INSERT)

        graph = Graph(module=models, select=["CleanMeasurement"])
        actual = join_sql_statements(
            Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True)
        )
        expected = """
        INSERT INTO builder.model_run (id, invocation_id, model_name)
        VALUES (:id, :invocation_id, :model_name);

        UPDATE builder.model_run
        SET status = :status, message = :message, duration = :duration
        WHERE id = :id;
        """
        assert_sql_equal(actual, expected)

        assert len(caplog.records) == 5
        assert "Started run" in caplog.records[0].message
        assert "Started running model 'CleanMeasurement'" in caplog.records[1].message
        assert (
            "Materialization 'delete+insert' is not implemented for views"
            in caplog.records[2].message
        )
        assert "Finished running model 'CleanMeasurement'" in caplog.records[3].message
        assert "Finished run" in caplog.records[4].message

    def test_view_external_materialization(
        self, clickhouse_adapter: ClickHouseAdapter, caplog, monkeypatch
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(CleanMeasurement, "__materialization__", Materialization.EXTERNAL)

        graph = Graph(module=models, select=["CleanMeasurement"])
        assert Runner(graph=graph, adapter=clickhouse_adapter).run(dry_run=True) == []

        assert len(caplog.records) == 2
        assert "Started run" in caplog.records[0].message
        assert "Finished run" in caplog.records[1].message
