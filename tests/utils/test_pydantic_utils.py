from dw_lib.utils.pydantic_utils import join_url
from pydantic import HttpUrl, ValidationError

import pytest


class TestJoinUrl:
    # --- Basic functionality ---

    def test_single_path_join(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "api")
        assert str(result) == "https://example.com/api"

    def test_multiple_path_join(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "api", "v1", "users")
        assert str(result) == "https://example.com/api/v1/users"

    def test_base_with_trailing_slash(self):
        base = HttpUrl("https://example.com/")
        result = join_url(base, "api")
        assert str(result) == "https://example.com/api"

    # --- Leading/trailing slash handling ---

    def test_paths_with_leading_slashes(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "/api", "/v1/", "/users/")
        assert str(result) == "https://example.com/api/v1/users"

    def test_paths_with_mixed_slashes(self):
        base = HttpUrl("https://example.com/")
        result = join_url(base, "api/", "/v1", "users/")
        assert str(result) == "https://example.com/api/v1/users"

    # --- Edge cases ---

    def test_no_paths_returns_base(self):
        base = HttpUrl("https://example.com")
        result = join_url(base)
        assert str(result) == "https://example.com/"

    def test_empty_path_segments(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "", "api", "", "v1")
        assert str(result) == "https://example.com/api/v1"

    def test_dot_segments(self):
        base = HttpUrl("https://example.com/api/")
        result = join_url(base, "..", "v1")
        # urljoin resolves ".."
        assert str(result) == "https://example.com/v1"

    def test_dot_current_directory(self):
        base = HttpUrl("https://example.com/api/")
        result = join_url(base, ".", "v1")
        assert str(result) == "https://example.com/api/v1"

    # --- Query params and fragments ---

    def test_base_with_query_params(self):
        base = HttpUrl("https://example.com?x=1")
        result = join_url(base, "api")
        # query is dropped by urljoin behavior
        assert str(result) == "https://example.com/api"

    def test_path_with_query_params(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "api?x=1")
        assert str(result) == "https://example.com/api?x=1"

    # --- Validation behavior ---

    def test_invalid_result_url_raises(self):
        base = HttpUrl("https://example.com")
        # invalid scheme introduced
        with pytest.raises(ValidationError):
            join_url(base, "http://[invalid-url]")

    def test_preserves_https_scheme(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "api")
        assert result.scheme == "https"

    def test_preserves_domain(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "api")
        assert result.host == "example.com"

    # --- Regression-style tricky cases ---

    def test_double_slash_prevention(self):
        base = HttpUrl("https://example.com/")
        result = join_url(base, "/api/", "/v1/")
        assert "//api" not in str(result)
        assert str(result) == "https://example.com/api/v1"

    def test_trailing_slash_removed_in_final_output(self):
        base = HttpUrl("https://example.com")
        result = join_url(base, "api/")
        assert not str(result).endswith("/")
        assert str(result) == "https://example.com/api"

    def test_multi_segment_equals_multiple_args(self):
        base = HttpUrl("https://example.com")

        result_single = join_url(base, "api/v1/users")
        result_multi = join_url(base, "api", "v1", "users")

        assert str(result_single) == "https://example.com/api/v1/users"
        assert result_single == result_multi
