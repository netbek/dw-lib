from packaging import version
from sqlglot.dialects.dialect import Dialects
from sqlmodel import SQLModel, Table

import datetime
import sqlglot
import sqlglot.expressions
import uuid

CLICKHOUSE_TYPES = [
    "AggregateFunction",
    "Array",
    "Boolean",
    "Date",
    "Date32",
    "DateTime",
    "DateTime64",
    "Decimal",
    "Enum",
    "Enum16",
    "Enum8",
    "Float",
    "Float32",
    "Float64",
    "IPv4",
    "IPv6",
    "Int",
    "Int128",
    "Int16",
    "Int256",
    "Int32",
    "Int64",
    "Int8",
    "LowCardinality",
    "Map",
    "Nested",
    "Nullable",
    "SimpleAggregateFunction",
    "String",
    "Tuple",
    "UInt128",
    "UInt16",
    "UInt256",
    "UInt32",
    "UInt64",
    "UInt8",
    "UUID",
]

SQLALCHEMY_TO_CLICKHOUSE_TYPE = {
    "Bool": "Boolean",
}

SQLGLOT_TO_PYTHON_TYPE = {
    sqlglot.expressions.DataType.Type.BIGINT: int,  # Int64
    sqlglot.expressions.DataType.Type.BOOLEAN: bool,  # Boolean
    sqlglot.expressions.DataType.Type.DATE32: datetime.date,  # Date32
    sqlglot.expressions.DataType.Type.DATETIME: datetime.datetime,  # DateTime
    sqlglot.expressions.DataType.Type.DATETIME64: datetime.datetime,  # DateTime64
    sqlglot.expressions.DataType.Type.DECIMAL: float,  # Decimal
    sqlglot.expressions.DataType.Type.DECIMAL32: float,  # Decimal32
    sqlglot.expressions.DataType.Type.DECIMAL64: float,  # Decimal64
    sqlglot.expressions.DataType.Type.DECIMAL128: float,  # Decimal128
    sqlglot.expressions.DataType.Type.DECIMAL256: float,  # Decimal256
    sqlglot.expressions.DataType.Type.DOUBLE: float,  # Float64
    sqlglot.expressions.DataType.Type.FLOAT: float,  # Float32
    sqlglot.expressions.DataType.Type.INT: int,  # Int32
    sqlglot.expressions.DataType.Type.SMALLINT: int,  # Int16
    sqlglot.expressions.DataType.Type.TEXT: str,  # String
    sqlglot.expressions.DataType.Type.TINYINT: int,  # Int8
    sqlglot.expressions.DataType.Type.UBIGINT: int,  # UInt64
    sqlglot.expressions.DataType.Type.UINT: int,  # UInt32
    sqlglot.expressions.DataType.Type.USMALLINT: int,  # UInt16
    sqlglot.expressions.DataType.Type.UTINYINT: int,  # UInt8
    sqlglot.expressions.DataType.Type.UUID: uuid.UUID,  # UUID
}

SQLGLOT_GTE_28_6 = version.parse(sqlglot.__version__) >= version.parse("28.6")


def get_model_schema(model: type[SQLModel]) -> str | None:
    table = getattr(model, "__table__", None)

    if isinstance(table, Table):
        return table.schema

    table_args = getattr(model, "__table_args__", None)

    if isinstance(table_args, dict):
        return table_args.get("schema")

    return None


def parse_create_table_statement(statement: str) -> dict:
    result = {
        "engine": None,
        "version": None,
        "is_deleted": None,
        "primary_key": [],
        "order_by": [],
        "settings": {},
        "columns": [],
    }
    parsed = sqlglot.parse_one(statement, dialect=Dialects.CLICKHOUSE)

    properties = parsed.args.get("properties")
    if properties:
        for prop in properties.expressions:
            # Table engine
            if isinstance(prop, sqlglot.exp.EngineProperty):
                engine_expr = prop.this

                # In SQLGlot v26.14.0, a table engine without settings was an instance of Var, not Identifier.
                # TODO Remove this after confirming it works in production and has test coverage (if not already)
                # if isinstance(engine_expr, sqlglot.exp.Var):
                #     result["engine"] = engine_expr.name

                if isinstance(engine_expr, sqlglot.exp.Identifier):
                    result["engine"] = engine_expr.name

                elif isinstance(engine_expr, sqlglot.exp.Anonymous):
                    result["engine"] = engine_expr.name

                    params = []
                    for arg_expr in engine_expr.expressions:
                        if isinstance(arg_expr, sqlglot.exp.Column) and isinstance(
                            arg_expr.this, sqlglot.exp.Identifier
                        ):
                            params.append(arg_expr.this.name)

                    if len(params) == 2:
                        result["version"] = params[0]
                        result["is_deleted"] = params[1]
                    elif len(params) == 1:
                        result["version"] = params[0]

            # Primary key
            elif isinstance(prop, sqlglot.exp.PrimaryKey):
                for primary_key_expr in prop.expressions:
                    if SQLGLOT_GTE_28_6:
                        if isinstance(primary_key_expr, sqlglot.exp.Identifier):
                            result["primary_key"].append(primary_key_expr.name)
                    else:
                        identifier = primary_key_expr.this.this
                        if isinstance(identifier, sqlglot.exp.Identifier):
                            result["primary_key"].append(identifier.name)

            # Order by
            elif isinstance(prop, sqlglot.exp.Order):
                for order_expr in prop.expressions:
                    inner = order_expr.this

                    # Single column
                    if isinstance(inner, sqlglot.exp.Column) and isinstance(
                        inner.this, sqlglot.exp.Identifier
                    ):
                        result["order_by"].append(inner.this.name)

                    # Multiple columns
                    elif isinstance(inner, sqlglot.exp.Tuple):
                        for column_expr in inner.expressions:
                            if isinstance(column_expr, sqlglot.exp.Column) and isinstance(
                                column_expr.this, sqlglot.exp.Identifier
                            ):
                                result["order_by"].append(column_expr.this.name)

            # Settings
            elif isinstance(prop, sqlglot.exp.SettingsProperty):
                for setting in prop.expressions:
                    key_expr = setting.this
                    val_expr = setting.expression

                    if isinstance(key_expr, sqlglot.exp.Column):
                        key = key_expr.name
                        if isinstance(val_expr, sqlglot.exp.Literal):
                            value = val_expr.this
                        else:
                            value = str(val_expr)
                        result["settings"][key] = value

    # Columns
    for node in parsed.find_all(sqlglot.exp.ColumnDef):
        name = node.name
        primary_key = name in result["primary_key"]
        nullable = node.kind.args.get("nullable")

        sqlglot_type = node.kind.args.get("this")
        python_type = SQLGLOT_TO_PYTHON_TYPE.get(sqlglot_type)
        sqlalchemy_type = to_sqlalchemy_type(node)

        if python_type is None:
            pydantic_type = "None"
        elif python_type.__module__ in ["datetime"]:
            pydantic_type = f"{python_type.__module__}.{python_type.__qualname__}"
            if nullable:
                pydantic_type = f"{pydantic_type} | None"
        else:
            pydantic_type = python_type.__qualname__
            if nullable:
                pydantic_type = f"{pydantic_type} | None"

        result["columns"].append(
            {
                "name": name,
                "primary_key": primary_key,
                "nullable": nullable,
                "sqlglot_type": sqlglot_type,
                "python_type": python_type,
                "pydantic_type": pydantic_type,
                "sqlalchemy_type": sqlalchemy_type,
            }
        )

    return result


def to_sqlalchemy_type(column_def: sqlglot.exp.ColumnDef) -> str:
    class ASTNode:
        pass

    class ArgumentNode(ASTNode):
        def __init__(self, value: str):
            self.value = value

        def __repr__(self):
            return self.value

    class SimpleTypeNode(ASTNode):
        def __init__(self, type_name: str):
            self.type_name = type_name

        def __repr__(self):
            return f"types.{self.type_name}"

    class NestedTypeNode(ASTNode):
        def __init__(self, modifier: str, inner: ASTNode):
            self.modifier = modifier
            self.inner = inner

        def __repr__(self):
            return f"types.{self.modifier}({self.inner})"

    def parse(string: str) -> ASTNode | None:
        if "(" in string and ")" in string:
            modifier, inner = string.split("(", 1)
            inner = inner.rsplit(")", 1)[0]  # Remove the outermost parentheses
            return NestedTypeNode(modifier.strip(), parse(inner.strip()))
        else:
            string = string.strip()

            if string in SQLALCHEMY_TO_CLICKHOUSE_TYPE:
                string = SQLALCHEMY_TO_CLICKHOUSE_TYPE[string]

            if string in CLICKHOUSE_TYPES:
                return SimpleTypeNode(string)
            else:
                return ArgumentNode(string)

    return parse(column_def.kind.sql(dialect=Dialects.CLICKHOUSE))
