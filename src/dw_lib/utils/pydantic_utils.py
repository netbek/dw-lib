from pydantic import HttpUrl, TypeAdapter, ValidationError
from urllib.parse import urljoin

URL_ADAPTER = TypeAdapter(HttpUrl)


def join_url(base: HttpUrl, *segments: str) -> HttpUrl:
    """Joins a Pydantic HttpUrl with path segments and returns a new HttpUrl."""
    url_str = str(base)
    if not url_str.endswith("/"):
        url_str += "/"

    try:
        for segment in segments:
            url_str = urljoin(url_str, segment.lstrip("/"))
            if not url_str.endswith("/"):
                url_str += "/"
    except ValueError as e:
        raise ValidationError.from_exception_data(
            title="Invalid URL during join", line_errors=[]
        ) from e

    url_str = url_str.rstrip("/")
    return URL_ADAPTER.validate_python(url_str)
