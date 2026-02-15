from ..conftest import DatabaseTest
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.dbt import Dbt
from pathlib import Path

import pytest


class InvocationTest(DatabaseTest):
    @pytest.fixture
    def profiles_dir(self):
        return Path(__file__).parent / "data" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self):
        return Path(__file__).parent / "data" / "invocation" / "dbt"

    @pytest.fixture
    def otlp_traces_endpoints(self):
        return ["http://localhost:20428/insert/opentelemetry/v1/traces"]


class TestRun(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, profiles_dir, project_dir):
        dbt = Dbt(profiles_dir=profiles_dir, project_dir=project_dir)
        runner_result = dbt.run()
        assert runner_result.success is True

    def test_success_with_traces(
        self,
        clickhouse_adapter: ClickHouseAdapter,
        profiles_dir,
        project_dir,
        otlp_traces_endpoints,
        monkeypatch,
    ):
        class _DummyExporter:
            instances = []

            def __init__(self, endpoint=None, **kwargs):
                self.endpoint = endpoint
                self.exported_spans = []
                _DummyExporter.instances.append(self)

            def export(self, spans):
                # store spans for inspection by the test
                self.exported_spans.extend(spans)
                return None

            def shutdown(self):
                return None

        monkeypatch.setattr("dw_lib.dbt.OTLPSpanExporter", _DummyExporter)

        class _ImmediateSpanProcessor:
            def __init__(self, exporter):
                self._exporter = exporter

            def on_start(self, span, parent_context):
                return None

            def on_end(self, span):
                # Export span synchronously for test inspection
                try:
                    self._exporter.export([span])
                except Exception:
                    pass

            def shutdown(self):
                return None

            def force_flush(self, timeout_millis=None):
                return None

        monkeypatch.setattr("dw_lib.dbt.BatchSpanProcessor", _ImmediateSpanProcessor)

        dbt = Dbt(
            profiles_dir=profiles_dir,
            project_dir=project_dir,
            otlp_traces_endpoints=otlp_traces_endpoints,
        )
        runner_result = dbt.run()
        assert runner_result.success is True

        # Collect exported spans from dummy exporters
        exporters = getattr(_DummyExporter, "instances", [])
        exported_spans = []
        for exp in exporters:
            exported_spans.extend(getattr(exp, "exported_spans", []))

        # There should be at least one root span and node spans
        root_spans = [s for s in exported_spans if s.name.startswith("dbt.invoke")]
        node_spans = [s for s in exported_spans if s.name.startswith("dbt.node.invoke")]

        assert root_spans, "no root invocation span exported"
        assert node_spans, "no node spans exported"

        # Verify node span attributes contain expected keys
        for s in node_spans:
            attrs = getattr(s, "attributes", {}) or {}
            assert "dbt.node.name" in attrs
            assert "dbt.node.resource_type" in attrs

        # Verify root span reports node count matching number of node results
        root_attrs = getattr(root_spans[0], "attributes", {}) or {}
        expected_node_count = len(runner_result.result.results)
        assert int(root_attrs.get("dbt.invoke.node_count", 0)) == expected_node_count


class TestSeed(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, profiles_dir, project_dir):
        dbt = Dbt(profiles_dir=profiles_dir, project_dir=project_dir)
        runner_result = dbt.seed()
        assert runner_result.success is True

    def test_success_with_traces(
        self,
        clickhouse_adapter: ClickHouseAdapter,
        profiles_dir,
        project_dir,
        otlp_traces_endpoints,
        monkeypatch,
    ):
        class _DummyExporter:
            instances = []

            def __init__(self, endpoint=None, **kwargs):
                self.endpoint = endpoint
                self.exported_spans = []
                _DummyExporter.instances.append(self)

            def export(self, spans):
                # store spans for inspection by the test
                self.exported_spans.extend(spans)
                return None

            def shutdown(self):
                return None

        monkeypatch.setattr("dw_lib.dbt.OTLPSpanExporter", _DummyExporter)

        class _ImmediateSpanProcessor:
            def __init__(self, exporter):
                self._exporter = exporter

            def on_start(self, span, parent_context):
                return None

            def on_end(self, span):
                # Export span synchronously for test inspection
                try:
                    self._exporter.export([span])
                except Exception:
                    pass

            def shutdown(self):
                return None

            def force_flush(self, timeout_millis=None):
                return None

        monkeypatch.setattr("dw_lib.dbt.BatchSpanProcessor", _ImmediateSpanProcessor)

        dbt = Dbt(
            profiles_dir=profiles_dir,
            project_dir=project_dir,
            otlp_traces_endpoints=otlp_traces_endpoints,
        )
        runner_result = dbt.seed()
        assert runner_result.success is True

        # Collect exported spans from dummy exporters
        exporters = getattr(_DummyExporter, "instances", [])
        exported_spans = []
        for exp in exporters:
            exported_spans.extend(getattr(exp, "exported_spans", []))

        # There should be at least one root span and node spans
        root_spans = [s for s in exported_spans if s.name.startswith("dbt.invoke")]
        node_spans = [s for s in exported_spans if s.name.startswith("dbt.node.invoke")]

        assert root_spans, "no root invocation span exported"
        assert node_spans, "no node spans exported"

        # Verify node span attributes contain expected keys
        for s in node_spans:
            attrs = getattr(s, "attributes", {}) or {}
            assert "dbt.node.name" in attrs
            assert "dbt.node.resource_type" in attrs

        # Verify root span reports node count matching number of node results
        root_attrs = getattr(root_spans[0], "attributes", {}) or {}
        expected_node_count = len(runner_result.result.results)
        assert int(root_attrs.get("dbt.invoke.node_count", 0)) == expected_node_count
