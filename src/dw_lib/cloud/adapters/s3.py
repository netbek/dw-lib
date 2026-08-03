from ..types import S3Settings
from botocore.client import Config
from typing import Any

import boto3


class S3Adapter:
    def __init__(self, settings: S3Settings) -> None:
        self.settings = settings

    @property
    def url(self) -> str:
        return f"s3://{self.settings.bucket}"

    def create_client(self):
        if self.settings.use_ssl:
            scheme = "https"
        else:
            scheme = "http"

        endpoint_url = f"{scheme}://{self.settings.endpoint}"

        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self.settings.key_id,
            aws_secret_access_key=self.settings.secret,
            config=Config(signature_version="s3v4"),
            region_name=self.settings.region,
        )

        return client

    def can_connect(self) -> bool:
        client = self.create_client()

        try:
            client.head_bucket(Bucket=self.settings.bucket)
        except Exception:  # noqa: BLE001
            return False

        return True

    def list_objects(self, prefix: str | None = None) -> list[dict[str, Any]]:
        client = self.create_client()
        response = client.list_objects_v2(Bucket=self.settings.bucket, Prefix=prefix)

        return response.get("Contents")
