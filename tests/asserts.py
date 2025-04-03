from collections import Counter

import re


def strip_whitespace(string: str) -> str:
    return re.sub(r"\s+", " ", string).strip()


def assert_equal_ignoring_whitespace(a, b):
    assert strip_whitespace(a) == strip_whitespace(b)


def assert_count_equal(a, b):
    """
    Asserts that two lists have the same elements, ignoring order.
    """
    assert isinstance(a, (list, tuple)), "a is not list or tuple"
    assert isinstance(b, (list, tuple)), "b is not list or tuple"

    def dict_to_tuple(d):
        if isinstance(d, dict):
            return tuple(sorted(d.items()))
        else:
            return d

    a_elements = sorted(map(dict_to_tuple, a))
    b_elements = sorted(map(dict_to_tuple, b))

    assert Counter(list(a_elements)) == Counter(list(b_elements)), "Lists have different elements"
