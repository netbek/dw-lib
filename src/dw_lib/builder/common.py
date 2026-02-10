from dw_lib.utils.profiling import timed
from enum import StrEnum
from pydantic import BaseModel
from sqlalchemy.engine.cursor import CursorResult
from sqlmodel import Session, text
from typing import Any

import logging
import re

# Example setup of logging of this module in your app:

# from rich.logging import RichHandler
# import logging
# import os

# logging.basicConfig(
#     level=os.getenv("LOG_LEVEL", "DEBUG").upper(),
#     format="%(message)s",
#     datefmt="[%Y-%m-%d %H:%M:%S.%f]",
#     handlers=[
#         RichHandler(
#             show_time=True,
#             show_level=True,
#             show_path=False,
#             markup=False,
#             rich_tracebacks=False,
#         )
#     ],
# )
# logging.getLogger("dw_lib").setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

RE_SELECT = re.compile(r"^\+?[A-Z0-9_]+\+?$", re.IGNORECASE)


class Materialization(StrEnum):
    CREATE = "create"
    CREATE_REPLACE = "create+replace"
    APPEND = "append"
    DELETE_INSERT = "delete+insert"
    EXTERNAL = "external"


class ModelRunStatus(StrEnum):
    SUCCESS = "success"  # Model run was successful
    ERROR = "error"  # Model run failed
    SKIPPED = "skipped"  # Model run was skipped because upstream dependency failed


class Statement(BaseModel):
    sql: str
    parameters: dict[str, Any] | None = None


def execute_statement(session: Session, statement: Statement) -> CursorResult[Any]:
    logger.debug(statement)

    with timed() as timing:
        result = session.exec(text(statement.sql), params=statement.parameters)

    logger.debug(f"Done in {timing.elapsed_seconds_formatted}")

    return result
