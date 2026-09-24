from ..conftest import DatabaseTest
from dbt.cli.main import dbtRunnerResult
from dbt.config.utils import parse_cli_yaml_string
from dbt_common.events.base_types import msg_from_base_event
from dbt_common.events.types import Note
from dw_lib.database import ClickHouseAdapter
from dw_lib.dbt import Dbt
from dw_lib.dbt.types import DbtDocsGenerateResult, DbtInvocationResult
from pathlib import Path
from typing import ClassVar

import json
import pytest
import shlex


class InvocationTest(DatabaseTest):
    @pytest.fixture
    def profiles_dir(self) -> Path:
        return Path(__file__).parent / "fixtures" / "invocation" / ".dbt"

    @pytest.fixture
    def project_dir(self) -> Path:
        return Path(__file__).parent / "fixtures" / "invocation" / "dbt"

    @pytest.fixture
    def dbt(self, profiles_dir, project_dir) -> Dbt:
        return Dbt(profiles_dir=profiles_dir, project_dir=project_dir)


def _make_fake_tracer(spans: list, record: bool = True):
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
                self.attributes[key] = (
                    int(value)
                    if isinstance(value, bool) is False and isinstance(value, (int,))
                    else value
                )
            except Exception:  # noqa: BLE001
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
            if record:
                spans.append(self.span)

        def __enter__(self):
            return self.span

        def __exit__(self, exc_type, exc, tb):
            if self.span.end_on_exit:
                self.span.end()
            return False

    class FakeTracer:
        def start_as_current_span(self, name, attributes=None, start_time=None, end_on_exit=True):
            return FakeCM(name, attributes, start_time, end_on_exit)

    return FakeTracer()


class TestBuild(InvocationTest):
    def test_success_tracing_disabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=False)
        )

        out = dbt.build(exclude="test_table")
        assert out.runner_result.success is True
        assert out.events == []
        assert spans == []

    def test_success_tracing_enabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.build(exclude="test_table")
        assert out.runner_result.success is True
        assert out.events == []

        root_spans = [s for s in spans if s.name.startswith("dbt.invoke")]
        assert root_spans, "no root span created"
        root = root_spans[0]
        assert int(root.attributes.get("dbt.invoke.node_count", 0)) > 0
        assert root.end_time is not None

        node_spans = [s for s in spans if s.name.startswith("dbt.node.invoke")]
        assert node_spans, "no node spans created"
        for ns in node_spans:
            assert ns.end_time is not None

    def test_capture_events(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.build(exclude="test_table", capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestRun(InvocationTest):
    def test_success_tracing_disabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=False)
        )

        out = dbt.run(exclude="test_table")
        assert out.runner_result.success is True
        assert out.events == []
        assert spans == []

    def test_success_tracing_enabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.run(exclude="test_table")
        assert out.runner_result.success is True
        assert out.events == []

        root_spans = [s for s in spans if s.name.startswith("dbt.invoke")]
        assert root_spans, "no root span created"
        root = root_spans[0]
        assert int(root.attributes.get("dbt.invoke.node_count", 0)) > 0
        assert root.end_time is not None

        node_spans = [s for s in spans if s.name.startswith("dbt.node.invoke")]
        assert node_spans, "no node spans created"
        for ns in node_spans:
            assert ns.end_time is not None

    def test_capture_events(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.run(exclude="test_table", capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestRunOperation(InvocationTest):
    def test_success_tracing_disabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=False)
        )

        out = dbt.run_operation("select_42")
        assert out.runner_result.success is True
        assert out.events == []
        assert spans == []

    def test_success_tracing_enabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.run_operation("select_42")
        assert out.runner_result.success is True
        assert out.events == []

        root_spans = [s for s in spans if s.name.startswith("dbt.invoke")]
        assert root_spans, "no root span created"
        root = root_spans[0]
        assert int(root.attributes.get("dbt.invoke.node_count", 0)) > 0
        assert root.end_time is not None

        node_spans = [s for s in spans if s.name.startswith("dbt.node.invoke")]
        assert node_spans, "no node spans created"
        for ns in node_spans:
            assert ns.end_time is not None

    def test_capture_events(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.run_operation("select_42", capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestSeed(InvocationTest):
    def test_success_tracing_disabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=False)
        )

        out = dbt.seed()
        assert out.runner_result.success is True
        assert out.events == []
        assert spans == []

    def test_success_tracing_enabled(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.seed()
        assert out.runner_result.success is True
        assert out.events == []

        root_spans = [s for s in spans if s.name.startswith("dbt.invoke")]
        assert root_spans, "no root span created"
        root = root_spans[0]
        assert int(root.attributes.get("dbt.invoke.node_count", 0)) > 0
        assert root.end_time is not None

        node_spans = [s for s in spans if s.name.startswith("dbt.node.invoke")]
        assert node_spans, "no node spans created"
        for ns in node_spans:
            assert ns.end_time is not None

    def test_capture_events(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.seed(capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestCompile(InvocationTest):
    def test_success(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        out = dbt.compile()
        assert out.runner_result.success is True
        assert out.events == []

    def test_capture_events(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt):
        out = dbt.compile(capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestParse(InvocationTest):
    def test_success(self, dbt: Dbt):
        out = dbt.parse()
        assert out.runner_result.success is True
        assert out.events == []

    def test_capture_events(self, dbt: Dbt):
        out = dbt.parse(capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestDocsGenerate(InvocationTest):
    def test_success(self, dbt: Dbt):
        out = dbt.docs_generate()
        assert out.runner_result.success is True
        assert out.events == []
        assert out.output_file.exists() is True

    def test_capture_events(self, dbt: Dbt):
        out = dbt.docs_generate(capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)
        assert out.output_file.exists() is True

        log_file = dbt.project_dir / "logs" / "dbt.log"
        assert log_file.exists() is True


class TestVarsFlag(InvocationTest):
    sample_vars: ClassVar[dict] = {
        "answer": 42,
        "enabled": True,
        "name": "example",
        "nested": {"a": [1, 2]},
    }

    builders: ClassVar[list] = [
        ("_build_command", {}),
        ("_compile_command", {}),
        ("_parse_command", {}),
        ("_run_command", {}),
        ("_run_operation_command", {"macro": "select_answer"}),
        ("_docs_generate_command", {}),
    ]

    @pytest.mark.parametrize("builder,kwargs", builders)
    def test_vars_flag_is_unquoted_json(self, dbt: Dbt, builder: str, kwargs: dict):
        cmd = getattr(dbt, builder)(**kwargs, vars=self.sample_vars)
        value = cmd[cmd.index("--vars") + 1]
        assert value == json.dumps(self.sample_vars)
        assert not value.startswith("'")
        assert not value.endswith("'")

    @pytest.mark.parametrize("builder,kwargs", builders)
    def test_vars_flag_round_trips_through_dbt_parser(self, dbt: Dbt, builder: str, kwargs: dict):
        cmd = getattr(dbt, builder)(**kwargs, vars=self.sample_vars)
        value = cmd[cmd.index("--vars") + 1]
        assert parse_cli_yaml_string(value, "vars") == self.sample_vars

    @pytest.mark.parametrize("builder,kwargs", builders)
    @pytest.mark.parametrize("vars_", [None, {}])
    def test_vars_flag_omitted_when_none_or_empty(
        self, dbt: Dbt, builder: str, kwargs: dict, vars_: dict | None
    ):
        cmd = getattr(dbt, builder)(**kwargs, vars=vars_)
        assert "--vars" not in cmd

    def test_args_flag_is_unquoted_json(self, dbt: Dbt):
        args = {"arg_1": "value_1"}
        cmd = dbt._run_operation_command("select_answer", args=args)
        value = cmd[cmd.index("--args") + 1]
        assert value == json.dumps(args)
        assert not value.startswith("'")
        assert not value.endswith("'")


class TestRunOperationVars(InvocationTest):
    def test_vars_passed_to_dbt(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        vars_ = {"answer": 42}
        out = dbt.run_operation("select_answer", vars=vars_)
        assert out.runner_result.success is True
        assert out.events == []

        root_spans = [s for s in spans if s.name.startswith("dbt.invoke")]
        assert root_spans, "no root span created"
        root = root_spans[0]
        expected_cmd = dbt._run_operation_command("select_answer", vars=vars_)
        assert root.attributes["dbt.invoke.raw_command"] == shlex.join(expected_cmd)

    def test_vars_required_when_missing(
        self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch
    ):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=False)
        )

        out = dbt.run_operation("select_answer")
        assert out.runner_result.success is False
        assert out.events == []

    def test_capture_events(self, clickhouse_adapter: ClickHouseAdapter, dbt: Dbt, monkeypatch):
        spans = []
        monkeypatch.setattr(
            "dw_lib.dbt.trace.get_tracer", lambda name: _make_fake_tracer(spans, record=True)
        )

        out = dbt.run_operation("select_answer", vars={"answer": 42}, capture_events=True)
        assert out.runner_result.success is True
        assert len(out.events) > 0
        assert all(isinstance(e.info.msg, str) for e in out.events)


def _make_event(msg: str):
    return msg_from_base_event(Note(msg=msg))


def _make_fake_dbt_runner(monkeypatch, events_to_fire=None, result=None):
    seen: dict = {}

    class FakeDbtRunner:
        def __init__(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs

        def invoke(self, args):
            seen["invoke_args"] = args
            for cb in seen["kwargs"].get("callbacks", []):
                for event in events_to_fire or []:
                    cb(event)
            return result or dbtRunnerResult(success=True)

    monkeypatch.setattr("dw_lib.dbt.dbtRunner", FakeDbtRunner)
    return seen


class TestResultDataclasses:
    def test_invocation_defaults(self):
        result = dbtRunnerResult(success=True)
        out = DbtInvocationResult(runner_result=result)
        assert out.runner_result is result
        assert out.events == []

    def test_docs_generate_defaults(self, tmp_path: Path):
        result = dbtRunnerResult(success=True)
        out = DbtDocsGenerateResult(runner_result=result, output_file=tmp_path / "index.html")
        assert out.runner_result is result
        assert out.output_file == tmp_path / "index.html"
        assert out.events == []


class TestInvokeHelper:
    def test_no_capture_passes_no_callbacks(self, monkeypatch):
        import dw_lib.dbt as dbt_module

        seen = _make_fake_dbt_runner(monkeypatch)
        cmd = ["dbt", "run", "--select", "my_model"]

        runner_result, events = dbt_module._invoke(cmd, False)

        assert runner_result.success is True
        assert events == []
        assert seen["kwargs"].get("callbacks", []) == []
        assert seen["invoke_args"] == cmd[1:]

    def test_capture_collects_real_events_in_order(self, monkeypatch):
        import dw_lib.dbt as dbt_module

        msg_one = _make_event("first")
        msg_two = _make_event("second")
        seen = _make_fake_dbt_runner(monkeypatch, events_to_fire=[msg_one, msg_two])
        cmd = ["dbt", "run", "--select", "my_model"]

        runner_result, events = dbt_module._invoke(cmd, True)

        assert runner_result.success is True
        assert events == [msg_one, msg_two]
        assert len(seen["kwargs"]["callbacks"]) == 1
        assert seen["invoke_args"] == cmd[1:]

    def test_per_call_isolation(self, monkeypatch):
        import dw_lib.dbt as dbt_module

        _make_fake_dbt_runner(monkeypatch, events_to_fire=[_make_event("x")])

        _, events_one = dbt_module._invoke(["dbt", "run"], True)
        _, events_two = dbt_module._invoke(["dbt", "run"], True)

        assert events_one is not events_two
        assert len(events_one) == 1
        assert len(events_two) == 1


class TestMethodCaptureWiring(InvocationTest):
    @pytest.mark.parametrize("method", ["build", "compile", "parse", "run", "seed"])
    def test_methods_forward_capture_events(self, dbt: Dbt, monkeypatch, method: str):
        import dw_lib.dbt as dbt_module

        calls: list = []
        fake_result = dbtRunnerResult(success=True)
        fake_events = [_make_event("wired")]

        def fake_invoke(cmd, capture_events):
            calls.append((cmd, capture_events))
            return fake_result, fake_events if capture_events else []

        monkeypatch.setattr(dbt_module, "_invoke", fake_invoke)
        monkeypatch.setattr(dbt_module, "_trace_invocation", lambda *args, **kwargs: None)

        out_default = getattr(dbt, method)()
        out_captured = getattr(dbt, method)(capture_events=True)

        assert isinstance(out_default, DbtInvocationResult)
        assert out_default.runner_result is fake_result
        assert out_default.events == []
        assert isinstance(out_captured, DbtInvocationResult)
        assert out_captured.events == fake_events
        assert calls[0][1] is False
        assert calls[1][1] is True

    def test_run_operation_forwards_capture_events(self, dbt: Dbt, monkeypatch):
        import dw_lib.dbt as dbt_module

        fake_result = dbtRunnerResult(success=True)
        monkeypatch.setattr(dbt_module, "_invoke", lambda cmd, capture_events: (fake_result, []))
        monkeypatch.setattr(dbt_module, "_trace_invocation", lambda *args, **kwargs: None)

        out = dbt.run_operation("select_42", capture_events=True)
        assert isinstance(out, DbtInvocationResult)
        assert out.runner_result is fake_result

    def test_docs_generate_forwards_capture_events(self, dbt: Dbt, monkeypatch, tmp_path: Path):
        import dw_lib.dbt as dbt_module

        fake_result = dbtRunnerResult(success=True)
        dest = tmp_path / "index.html"
        monkeypatch.setattr(dbt_module, "_invoke", lambda cmd, capture_events: (fake_result, []))
        monkeypatch.setattr(dbt_module, "bundle_docs", lambda project_dir: dest)

        out = dbt.docs_generate()
        assert isinstance(out, DbtDocsGenerateResult)
        assert out.runner_result is fake_result
        assert out.output_file == dest
        assert out.events == []
