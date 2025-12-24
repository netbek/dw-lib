from dw_lib.utils.profiling import timed

import pytest
import time


class TimedError(Exception): ...


class TestTimed:
    def test_success(self):
        with timed() as result:
            time.sleep(1)
        assert result.elapsed_ms == 1000
        assert result.elapsed_ms_formatted == "1000 ms"
        assert result.elapsed_seconds_formatted == "1.00 s"

    def test_failure(self):
        with pytest.raises(TimedError):
            with timed() as result:
                time.sleep(1)
                raise TimedError()
        assert result.elapsed_ms == 1000
        assert result.elapsed_ms_formatted == "1000 ms"
        assert result.elapsed_seconds_formatted == "1.00 s"
