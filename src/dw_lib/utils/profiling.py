import contextlib
import cProfile
import io
import pstats


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
