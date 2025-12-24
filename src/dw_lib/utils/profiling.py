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
    elapsed_seconds: float = 0.0

    @property
    def elapsed_ms(self) -> int:
        return int(self.elapsed_seconds * 1000)

    @property
    def elapsed_seconds_formatted(self) -> str:
        return f"{self.elapsed_seconds:.2f} s"

    @property
    def elapsed_ms_formatted(self) -> str:
        return f"{self.elapsed_ms} ms"


@contextmanager
def timed():
    start = time.perf_counter()
    result = TimeResult()
    try:
        yield result
    finally:
        result.elapsed_seconds = time.perf_counter() - start
