from sqlmodel import SQLModel, Table


def get_model_schema(model: type[SQLModel]) -> str | None:
    table = getattr(model, "__table__", None)

    if isinstance(table, Table):
        return table.schema

    table_args = getattr(model, "__table_args__", None)

    if isinstance(table_args, dict):
        return table_args.get("schema")

    return None
