from pydantic import BaseModel


class S3Settings(BaseModel):
    key_id: str
    secret: str
    region: str
    endpoint: str
    use_ssl: bool
    url_style: str = "path"
    bucket: str
    prefix: str | None = None
