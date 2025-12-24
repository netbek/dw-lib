from contextlib import contextmanager
from dataclasses import dataclass

import contextlib
import cProfile
import io
import pstats
import time


@contextlib.contextmanager
def profiled():
    """
    Source: https://docs.sqlalchemy.org/en/14/faq/performance.html#code-profiling
    """
    pr = cProfile.Profile()
    pr.enable()
    yield
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative").reverse_order()
    ps.print_stats()
    # uncomment this to see who's calling what
    # ps.print_callers()
    print(s.getvalue())


@dataclass
class TimeResult:
    elapsed: float = 0.0
    elapsed_formatted: str = ""


@contextmanager
def timed():
    start = time.perf_counter()
    result = TimeResult()
    try:
        yield result
    finally:
        result.elapsed = time.perf_counter() - start
        result.elapsed_formatted = (
            f"{result.elapsed:.2f} {'second' if int(result.elapsed) == 1 else 'seconds'}"
        )
