from collections import Counter

import re


def strip_whitespace(string: str) -> str:
    return re.sub(r"\s+", " ", string).strip()


def assert_equal_ignoring_whitespace(actual, expected):
    assert strip_whitespace(actual) == strip_whitespace(expected)


def assert_count_equal(a, b):
    """
    Asserts that two lists have the same elements, ignoring order.
    """
    assert Counter(list(a)) == Counter(list(b)), "Lists have different elements"


def assert_count_equal_dicts(a, b):
    """
    Asserts that two lists of dictionaries have the same elements, ignoring order.
    """
    assert len(a) == len(b), "Lists have different lengths"

    def dict_to_tuple(d):
        return tuple(sorted(d.items()))

    a_tuples = sorted(map(dict_to_tuple, a))
    b_tuples = sorted(map(dict_to_tuple, b))

    assert a_tuples == b_tuples, "Lists have different elements"
