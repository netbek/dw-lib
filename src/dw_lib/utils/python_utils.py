from ..constants import PYTHON_KEYWORDS
from functools import lru_cache


@lru_cache
def is_python_keyword(value: str) -> bool:
    return value.lower() in PYTHON_KEYWORDS
