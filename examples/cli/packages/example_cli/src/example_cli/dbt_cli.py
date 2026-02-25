from .dbt_docs_cli import dbt_docs_app
from .root import app
from .settings import get_settings
from dw_lib.database import ClickHouseAdapter
from dw_lib.dbt import Dbt
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

import dbt.version
import rich
import typer

dbt_app = typer.Typer(name="dbt")
dbt_app.add_typer(dbt_docs_app)
app.add_typer(dbt_app)
console = rich.console.Console()
settings = get_settings()
dbt_ = Dbt()

resource = Resource.create({SERVICE_NAME: "cli"})
tracer_provider = TracerProvider(resource=resource)
span_processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:20428/insert/opentelemetry/v1/traces")
)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)


@dbt_app.command()
def version():
    """Print dbt version."""
    console.print(dbt.version.__version__)


@dbt_app.command()
def list_resources():
    """List project resources."""
    for resource in dbt_.list_resources():
        console.print(f"{resource.resource_type}: {resource.name}")


@dbt_app.command()
def generate_source_yaml(database: str) -> None:
    """Generate dbt source YAML."""
    adapter = ClickHouseAdapter(settings.database)
    data = dbt_.generate_source_yaml(
        adapter,
        database=database,
        table_pattern=f"raw_{database}_%",
        source_props={
            "loader": "peerdb",
            "config": {
                "loaded_at_field": "_peerdb_synced_at",
            },
        },
    )
    file = dbt_.models_dir / "staging" / database / "sources.yml"
    with open(file, "w") as fp:
        fp.write(data)
    console.print(f"Written to {file}", style="green")


@dbt_app.command()
def generate_model_yaml(database: str) -> None:
    """Generate dbt model YAML."""
    adapter = ClickHouseAdapter(settings.database)
    data = dbt_.generate_model_yaml(
        adapter,
        database=database,
        table_pattern=f"stg_{database}_%",
    )
    for table_name, yaml in data.items():
        file = dbt_.models_dir / "staging" / database / f"{table_name}.yml"
        with open(file, "w") as fp:
            fp.write(yaml)
        console.print(f"Written to {file}", style="green")


@dbt_app.command()
def run():
    """Compile SQL and execute against the target database."""
    dbt_.run()


@dbt_app.command()
def seed():
    """Load data from CSV files into the target database."""
    dbt_.seed()


@dbt_app.command()
def run_operation(macro: str):
    """Run a named macro."""
    dbt_.run_operation(macro)
