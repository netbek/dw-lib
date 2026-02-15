from ..conftest import DatabaseTest
from dw_lib.database.adapters import ClickHouseAdapter
from dw_lib.dbt import Dbt
from pathlib import Path

import pytest


class InvocationTest(DatabaseTest):
    @pytest.fixture
    def profiles_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self) -> Path:
        return Path(__file__).parent / "data" / "invocation" / "dbt"

    @pytest.fixture
    def dbt(self, profiles_dir, project_dir) -> Dbt:
        return Dbt(profiles_dir=profiles_dir, project_dir=project_dir)


class TestRun(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        runner_result = dbt.run()
        assert runner_result.success is True


class TestRunOperation(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        runner_result = dbt.run_operation("select_42")
        assert runner_result.success is True


class TestSeed(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        runner_result = dbt.seed()
        assert runner_result.success is True


class TestTracing(InvocationTest):
    def test_spans_exported(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []

        class FakeSpan:
            def __init__(self, name, attributes, start_time, end_on_exit):
                self.name = name
                self.attributes = attributes or {}
                self.start_time = start_time
                self.end_on_exit = end_on_exit
                self.end_time = None
                self.events = []
                self.status = None

            def end(self, end_time=None):
                self.end_time = end_time

            def set_status(self, status):
                self.status = status

            def set_attribute(self, key, value):
                try:
                    # coerce ints/floats/strings
                    self.attributes[key] = (
                        int(value)
                        if isinstance(value, bool) is False and isinstance(value, (int,))
                        else value
                    )
                except Exception:
                    self.attributes[key] = value

            def set_attributes(self, attrs: dict):
                if not attrs:
                    return
                for k, v in attrs.items():
                    self.set_attribute(k, v)

            def add_event(self, name, attributes=None):
                self.events.append((name, attributes))

            def record_exception(self, exc):
                self.attributes["exception"] = str(exc)

            def is_recording(self):
                return True

        class FakeCM:
            def __init__(self, name, attributes, start_time, end_on_exit):
                self.span = FakeSpan(name, attributes, start_time, end_on_exit)
                spans.append(self.span)

            def __enter__(self):
                return self.span

            def __exit__(self, exc_type, exc, tb):
                if self.span.end_on_exit:
                    self.span.end()
                return False

        class FakeTracer:
            def start_as_current_span(
                self, name, attributes=None, start_time=None, end_on_exit=True
            ):
                return FakeCM(name, attributes, start_time, end_on_exit)

        monkeypatch.setattr("dw_lib.dbt.trace.get_tracer", lambda name: FakeTracer())

        runner_result = dbt.run()
        assert runner_result.success is True

        # confirm a root invoke span was created and ended
        root_spans = [s for s in spans if s.name.startswith("dbt.invoke")]
        assert root_spans, "no root span created"
        root = root_spans[0]
        assert int(root.attributes.get("dbt.invoke.node_count", 0)) > 0
        assert root.end_time is not None

        # confirm node spans were created and ended
        node_spans = [s for s in spans if s.name.startswith("dbt.node.invoke")]
        assert node_spans, "no node spans created"
        for ns in node_spans:
            assert ns.end_time is not None
