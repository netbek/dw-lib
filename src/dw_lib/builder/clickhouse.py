from clickhouse_sqlalchemy import engines
from collections.abc import Sequence
from dw_lib.builder.common import (
    execute_statement,
    logger,
    Materialization,
    ModelRunStatus,
    RE_SELECT,
)
from dw_lib.database import ClickHouseAdapter
from dw_lib.types import ClickHouseRelation
from dw_lib.utils.profiling import timed
from dw_lib.utils.sqlmodel_utils import get_model_schema
from pydantic import BaseModel, ConfigDict, field_validator, PrivateAttr
from rich.table import Table
from sqlmodel import SQLModel
from types import ModuleType
from typing import Any, ClassVar, TypeAlias

import networkx as nx
import networkx_mermaid as nxm
import pydash
import re
import uuid

# Registry is used to keep track of all defined relations
RELATION_REGISTRY: list[type["BaseRelation"]] = []


class RelationMeta(type(SQLModel)):
    def __new__(mcs, name, bases, attrs, **kwargs):
        # Create the class, passing the kwargs up to SQLModel's metaclass
        cls = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Add to registry
        if name not in ("BaseRelation", "BaseTable", "BaseView"):
            RELATION_REGISTRY.append(cls)

        # Dynamic dependency discovery
        sql = attrs.get("__sql__")
        if sql and isinstance(sql, str):
            found_deps = []
            for other_cls in RELATION_REGISTRY:
                if other_cls == cls:
                    continue

                # Check for the relation string in the SQL
                relation_str = str(other_cls)
                pattern = rf"\b{re.escape(relation_str)}\b"

                if re.search(pattern, sql):
                    found_deps.append(other_cls)

            # Populate __depends_on__ if empty
            if found_deps and not attrs.get("__depends_on__"):
                cls.__depends_on__ = tuple(found_deps)

        return cls

    def __str__(cls) -> str:
        return str(cls.make_relation())


class BaseRelation(SQLModel, metaclass=RelationMeta):
    model_config = ConfigDict(frozen=True)
    __tablename__: ClassVar[str]
    __materialization__: ClassVar[Materialization] = Materialization.CREATE
    __depends_on__: ClassVar[Sequence[type["BaseTable | BaseView"]]] = ()
    __table_args__: ClassVar[tuple[Any, ...]] = ()
    __sql__: ClassVar[str | None] = None

    @classmethod
    def make_relation(cls) -> ClickHouseRelation:
        return ClickHouseRelation(table=cls.__tablename__, database=get_model_schema(cls))

    @classmethod
    def make_create_statement(cls, adapter: ClickHouseAdapter) -> str | None:
        raise NotImplementedError


class BaseTable(BaseRelation):
    __unique_key__: ClassVar[str | list[str] | None] = None
    __table_args__: ClassVar[tuple[Any, ...]] = (engines.MergeTree(),)

    @classmethod
    def make_create_statement(cls, adapter: ClickHouseAdapter) -> str | None:
        if cls.__materialization__ == Materialization.EXTERNAL:
            return None  # Ignore externally managed tables
        return adapter.make_create_table_statement_from_model(cls, pretty=True, pad=4)


class BaseView(BaseRelation):
    __sql__: ClassVar[str]

    @classmethod
    def make_create_statement(cls, adapter: ClickHouseAdapter) -> str:
        return adapter.make_create_view_statement_from_model(cls, cls.__sql__, pretty=True, pad=4)


ModelType: TypeAlias = type[BaseTable | BaseView]
ModelCollection: TypeAlias = Sequence[ModelType]


class Graph(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    module: ModuleType
    select: list[str] | None = None
    _graph: nx.DiGraph | None = PrivateAttr(default=None)
    _models: tuple[ModelType] | None = PrivateAttr(default=None)

    @field_validator("select")
    @classmethod
    def validate_select(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value

        if not isinstance(value, list):
            raise TypeError("Select must be a list of strings")

        for select in value:
            if not isinstance(select, str):
                raise TypeError("Each select item must be a string")

            if not RE_SELECT.fullmatch(select):
                raise ValueError(
                    f"Invalid select '{select}'. Expected formats: Model, +Model, Model+, +Model+"
                )

        return value

    @property
    def graph(self) -> nx.DiGraph:
        if self._graph is None:
            models = []
            for name in getattr(self.module, "__all__", ()):
                obj = getattr(self.module, name)
                if isinstance(obj, type) and (
                    issubclass(obj, BaseTable) or issubclass(obj, BaseView)
                ):
                    models.append(obj)

            graph = self._make_graph(models)
            if self.select:
                graph = self._make_subgraph(graph, self.select)
            self._graph = graph

        return self._graph

    @property
    def models(self) -> tuple[ModelType]:
        if self._models is None:
            self._models = tuple(
                nx.lexicographical_topological_sort(
                    self.graph, key=lambda model: self._format_relation(model.make_relation())
                )
            )

        return self._models

    # def render_graph(self) -> str:
    #     names = get_names_from_select(self.select)
    #     mapping = {node: self._format_name(node, names) for node in self.graph.nodes}
    #     graph = nx.relabel_nodes(self.graph, mapping, copy=True)
    #     lines = list(nx.generate_network_text(graph))
    #     if "╙──" in lines[0] or "╟──" in lines[0]:
    #         lines = [line[3:] for line in lines]
    #     diagram = "\n".join(lines)

    #     return diagram

    def render_list(self) -> Table:
        select_names = self._get_names_from_select(self.select)
        table = Table()
        table.add_column("Model")
        table.add_column("Relation")
        table.add_column("Type")
        table.add_column("Materialization")

        for model in self.models:
            table.add_row(
                model.__name__,
                self._format_relation(model.make_relation()),
                self._format_type(model),
                model.__materialization__,
                style="bold yellow" if select_names and model.__name__ in select_names else None,
            )

        return table

    def render_markdown(self) -> str:
        builder = nxm.builders.DiagramBuilder()
        mapping = {node: node.__name__ for node in self.graph.nodes}
        graph = nx.relabel_nodes(self.graph, mapping, copy=True)
        diagram = builder.build(graph)

        return nxm.formatters.markdown(diagram)

    def _get_names_from_select(self, select: list[str] | None) -> list[str] | None:
        if select is None:
            return select
        else:
            return [selector.strip("+") for selector in select]

    # def _format_name(self, model: ModelType, select_names: list[str] | None) -> str:
    #     if select_names and model.__name__ in select_names:
    #         return f"[b][yellow]{model.__name__}[/yellow][/b]"
    #     else:
    #         return model.__name__

    def _format_relation(self, relation: ClickHouseRelation) -> str:
        if relation.database:
            return f"{relation.database}.{relation.table}"
        else:
            return relation.table

    def _format_type(self, model: ModelType) -> str:
        if issubclass(model, BaseTable):
            return "table"
        elif issubclass(model, BaseView):
            return "view"
        else:
            return "-"

    def _make_graph(self, models: ModelCollection) -> nx.DiGraph:
        graph = nx.DiGraph()

        # Add all models as nodes
        graph.add_nodes_from(models)

        # Add dependency edges
        for model in models:
            for dep in getattr(model, "__depends_on__", ()):
                if dep not in models:
                    raise ValueError(
                        f"{model.__name__} depends on {dep.__name__}, "
                        "but it is not in the provided model list"
                    )
                graph.add_edge(dep, model)

        # Validate DAG
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("Cycle detected in model dependencies")

        return graph

    def _make_subgraph(self, graph: nx.DiGraph, select: list[str]) -> nx.DiGraph:
        """
        Create a subgraph using a comma-delimited selector.

        Selector examples:
            "Taxon"              -> model only
            "+Taxon"             -> model + ancestors
            "Taxon+"             -> model + descendants
            "+Taxon+"            -> model + ancestors + descendants
            "Taxon,Distribution" -> multiple models
        """
        mapping = {model.__name__: model for model in graph.nodes}
        selected: set[ModelType] = set()

        for selector in select:
            upstream = selector.startswith("+")
            downstream = selector.endswith("+")
            name = selector.strip("+")

            if not name:
                raise ValueError(f"Invalid selector '{selector}'")

            if name not in mapping:
                raise KeyError(f"Model '{name}' not found in DAG")

            model = mapping[name]
            subset: set[ModelType] = {model}

            if upstream:
                subset |= nx.ancestors(graph, model)

            if downstream:
                subset |= nx.descendants(graph, model)

            selected |= subset

        return graph.subgraph(selected).copy()


class Runner(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    graph: Graph
    adapter: ClickHouseAdapter
    dw_schema: str | None = "dw"

    def run(self) -> None:
        skipped_models = set()
        models = pydash.filter_(
            self.graph.models,
            lambda model: (
                get_model_schema(model) != self.dw_schema
                and model.__materialization__ != Materialization.EXTERNAL
            ),
        )
        ModelRun: ModelType = pydash.find(
            self.graph.models,
            lambda model: (
                get_model_schema(model) == self.dw_schema and model.__name__ == "ModelRun"
            ),
        )
        invocation_id = uuid.uuid4()
        logger.info(f"Started run {invocation_id}")

        with timed() as invocation_timing, self.adapter.create_session() as session:
            for model in models:
                model_run_id = uuid.uuid4()

                # Skip this model because its upstream dependency failed
                if model in skipped_models:
                    logger.info(f"Skipped running model '{model.__name__}'")
                    statement = f"""
                        INSERT INTO {ModelRun} (id, invocation_id, model_name, status)
                        VALUES (:id, :invocation_id, :model_name, :status)
                        """
                    parameters = {
                        "id": model_run_id,
                        "invocation_id": invocation_id,
                        "model_name": model.__name__,
                        "status": ModelRunStatus.SKIPPED,
                    }
                    execute_statement(session, statement, parameters=parameters)
                    continue

                logger.info(f"Started running model '{model.__name__}'")
                statement = f"""
                    INSERT INTO {ModelRun} (id, invocation_id, model_name)
                    VALUES (:id, :invocation_id, :model_name)
                    """
                parameters = {
                    "id": model_run_id,
                    "invocation_id": invocation_id,
                    "model_name": model.__name__,
                }
                execute_statement(session, statement, parameters=parameters)

                with timed() as model_run_timing:
                    try:
                        message = self._run_model(self.adapter, model)
                        status = ModelRunStatus.SUCCESS
                    except Exception as exc_info:
                        message = str(exc_info)
                        status = ModelRunStatus.ERROR
                        logger.error(message, exc_info=exc_info)

                if message:
                    log_result = f"{status.title()} ({message})"
                else:
                    log_result = f"{status.title()}"

                logger.info(
                    f"Finished running model '{model.__name__}' after {model_run_timing.elapsed_seconds_formatted}. "
                    f"Result: {log_result}"
                )
                statement = f"""
                    UPDATE {ModelRun}
                    SET status = :status, message = :message, duration = :duration
                    WHERE id = :id
                    """
                parameters = {
                    "id": model_run_id,
                    "status": status,
                    "message": message if message else "",
                    "duration": model_run_timing.elapsed_ms,
                }
                execute_statement(session, statement, parameters=parameters)

                if status == ModelRunStatus.ERROR:
                    # Flag the models that must be skipped because their upstream dependency failed
                    skipped_models.update(nx.descendants(self.graph.graph, model))

        logger.info(
            f"Finished run {invocation_id} after {invocation_timing.elapsed_seconds_formatted}"
        )

    def _make_intermediate_relation(
        self, table: str, database: str | None = None
    ) -> ClickHouseRelation:
        return ClickHouseRelation(table=f"{table}__tmp", database=database)

    def _run_model(
        self, adapter: ClickHouseAdapter, model: ModelType, use_alembic: bool = True
    ) -> str | None:
        target_relation = ClickHouseRelation(
            table=model.__tablename__, database=get_model_schema(model)
        )
        materialization = model.__materialization__
        sql = model.__sql__

        if issubclass(model, BaseTable):
            unique_key = model.__unique_key__

            if materialization == Materialization.CREATE:
                if use_alembic:
                    return
                else:
                    with adapter.create_session() as session:
                        if not adapter.has_table(
                            table=target_relation.table, database=target_relation.database
                        ):
                            # Create target table
                            statement = adapter.make_create_table_statement_from_model(
                                model,
                                table=target_relation.table,
                                database=target_relation.database,
                                sql=sql,
                            )
                            execute_statement(session, statement)

            elif materialization == Materialization.CREATE_REPLACE:
                with adapter.create_session() as session:
                    if use_alembic:
                        intermediate_relation = self._make_intermediate_relation(
                            table=target_relation.table, database=target_relation.database
                        )

                        # Drop intermediate table if it exists
                        statement = f"DROP TABLE IF EXISTS {intermediate_relation}"
                        execute_statement(session, statement)

                        # Create intermediate table
                        statement = f"CREATE TABLE {intermediate_relation} AS {target_relation}"
                        execute_statement(session, statement)

                        statement = f"INSERT INTO {intermediate_relation} ({sql})"
                        execute_statement(session, statement)

                        # Do atomic swap of intermediate and target tables
                        statement = f"EXCHANGE TABLES {target_relation} AND {intermediate_relation}"
                        execute_statement(session, statement)

                        # Drop intermediate table
                        statement = f"DROP TABLE {intermediate_relation}"
                        execute_statement(session, statement)
                    else:
                        if adapter.has_table(
                            table=target_relation.table, database=target_relation.database
                        ):
                            intermediate_relation = self._make_intermediate_relation(
                                table=target_relation.table, database=target_relation.database
                            )

                            # Drop intermediate table if it exists
                            statement = f"DROP TABLE IF EXISTS {intermediate_relation}"
                            execute_statement(session, statement)

                            # Create intermediate table
                            statement = adapter.make_create_table_statement_from_model(
                                model,
                                table=intermediate_relation.table,
                                database=intermediate_relation.database,
                                sql=sql,
                            )
                            execute_statement(session, statement)

                            # Do atomic swap of intermediate and target tables
                            statement = (
                                f"EXCHANGE TABLES {target_relation} AND {intermediate_relation}"
                            )
                            execute_statement(session, statement)

                            # Drop intermediate table
                            statement = f"DROP TABLE {intermediate_relation}"
                            execute_statement(session, statement)
                        else:
                            # Create target table
                            statement = adapter.make_create_table_statement_from_model(
                                model,
                                table=target_relation.table,
                                database=target_relation.database,
                                sql=sql,
                            )
                            execute_statement(session, statement)

            elif materialization == Materialization.APPEND:
                raise NotImplementedError()

            elif materialization == Materialization.DELETE_INSERT:
                if not unique_key:
                    raise ValueError(
                        f"{model.__name__}.__unique_key__ must be set when materialization = "
                        f"'{Materialization.DELETE_INSERT.value}'"
                    )

                if not sql:
                    raise ValueError(
                        f"{model.__name__}.__sql__ must be set when materialization = "
                        f"'{Materialization.DELETE_INSERT.value}'"
                    )

                with adapter.create_session() as session:
                    if use_alembic:
                        intermediate_relation = self._make_intermediate_relation(
                            table=target_relation.table, database=target_relation.database
                        )

                        # Drop intermediate table if it exists
                        statement = f"DROP TABLE IF EXISTS {intermediate_relation}"
                        execute_statement(session, statement)

                        # Create intermediate table
                        statement = f"CREATE TABLE {intermediate_relation} AS {target_relation}"
                        execute_statement(session, statement)

                        statement = f"INSERT INTO {intermediate_relation} ({sql})"
                        execute_statement(session, statement)

                        # Delete matching rows from target table
                        if isinstance(unique_key, str):
                            unique_keys = [unique_key]
                        else:
                            unique_keys = list(unique_key)

                        if len(unique_keys) == 1:
                            key = unique_keys[0]
                            statement = f"""
                                DELETE FROM {target_relation}
                                WHERE {key} IN (
                                    SELECT {key} FROM {intermediate_relation}
                                )
                                """
                        else:
                            keys_csv = ", ".join(unique_keys)
                            statement = f"""
                                DELETE FROM {target_relation}
                                WHERE ({keys_csv}) IN (
                                    SELECT {keys_csv} FROM {intermediate_relation}
                                )
                                """
                        execute_statement(session, statement)

                        # Insert new data into target table
                        statement = f"""
                            INSERT INTO {target_relation}
                            SELECT * FROM {intermediate_relation}
                            """
                        execute_statement(session, statement)

                        # Drop intermediate table
                        statement = f"DROP TABLE {intermediate_relation}"
                        execute_statement(session, statement)
                    else:
                        if adapter.has_table(
                            table=target_relation.table, database=target_relation.database
                        ):
                            intermediate_relation = self._make_intermediate_relation(
                                table=target_relation.table, database=target_relation.database
                            )

                            # Drop intermediate table if it exists
                            statement = f"DROP TABLE IF EXISTS {intermediate_relation}"
                            execute_statement(session, statement)

                            # Create intermediate table
                            statement = adapter.make_create_table_statement_from_model(
                                model,
                                table=intermediate_relation.table,
                                database=intermediate_relation.database,
                                sql=sql,
                            )
                            execute_statement(session, statement)

                            # Delete matching rows from target table
                            if isinstance(unique_key, str):
                                unique_keys = [unique_key]
                            else:
                                unique_keys = list(unique_key)

                            if len(unique_keys) == 1:
                                key = unique_keys[0]
                                statement = f"""
                                    DELETE FROM {target_relation}
                                    WHERE {key} IN (
                                        SELECT {key} FROM {intermediate_relation}
                                    )
                                    """
                            else:
                                keys_csv = ", ".join(unique_keys)
                                statement = f"""
                                    DELETE FROM {target_relation}
                                    WHERE ({keys_csv}) IN (
                                        SELECT {keys_csv} FROM {intermediate_relation}
                                    )
                                    """
                            execute_statement(session, statement)

                            # Insert new data into target table
                            statement = f"""
                                INSERT INTO {target_relation}
                                SELECT * FROM {intermediate_relation}
                                """
                            execute_statement(session, statement)

                            # Drop intermediate table
                            statement = f"DROP TABLE {intermediate_relation}"
                            execute_statement(session, statement)
                        else:
                            return

            elif materialization == Materialization.EXTERNAL:
                return

            else:
                raise AttributeError(f"Materialization '{materialization}' is not supported")

        elif issubclass(model, BaseView):
            if materialization == Materialization.CREATE:
                if use_alembic:
                    return
                else:
                    with adapter.create_session() as session:
                        statement = f"CREATE VIEW IF NOT EXISTS {target_relation} AS ({sql})"
                        execute_statement(session, statement)

            elif materialization == Materialization.CREATE_REPLACE:
                if use_alembic:
                    return
                else:
                    with adapter.create_session() as session:
                        statement = f"CREATE OR REPLACE VIEW {target_relation} AS ({sql})"
                        execute_statement(session, statement)

            elif materialization == Materialization.EXTERNAL:
                return

            else:
                raise AttributeError(f"Materialization '{materialization}' is not supported")

        else:
            raise Exception("Model must be subclass of BaseTable or BaseView")
