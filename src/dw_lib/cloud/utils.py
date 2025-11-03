from urllib.parse import urlparse


def s3_to_endpoint_uri(s3_uri: str, endpoint: str, use_ssl: bool = False) -> str:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid S3 URI: {s3_uri}")

    if use_ssl:
        scheme = "https"
    else:
        scheme = "http"

    bucket = parsed.netloc
    path = parsed.path.lstrip("/")

    return f"{scheme}://{endpoint}/{bucket}/{path}"
