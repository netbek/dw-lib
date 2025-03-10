def assert_list_of_dicts_equal_ignore_order(a, b):
    """
    Asserts that two lists of dictionaries have the same elements, ignoring order.
    """
    assert len(a) == len(b), "Lists have different lengths"

    def dict_to_tuple(d):
        return tuple(sorted(d.items()))

    a_tuples = sorted(map(dict_to_tuple, a))
    b_tuples = sorted(map(dict_to_tuple, b))

    assert a_tuples == b_tuples, "Lists have different elements"
