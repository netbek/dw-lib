from abc import ABC, abstractmethod
from contextlib import contextmanager
from pydantic import BaseModel
from sqlalchemy import create_engine, URL
from typing import overload


class BaseAdapter(ABC):
    def __init__(self, settings: BaseModel) -> None:
        self.settings = settings

    @overload
    @classmethod
    @abstractmethod
    def create_url(
        cls, host: str, port: int, username: str, password: str, database: str, schema: str
    ) -> URL: ...

    @overload
    @classmethod
    @abstractmethod
    def create_url(cls, database: str, schema: str) -> URL: ...

    @classmethod
    @abstractmethod
    def create_url(cls, *args, **kwargs) -> URL: ...

    @abstractmethod
    def create_client(): ...

    @contextmanager
    def create_engine(self):
        engine = create_engine(self.url, echo=False)

        yield engine

        engine.dispose()

    @contextmanager
    @abstractmethod
    def create_session(): ...

    @abstractmethod
    def can_connect(self) -> bool: ...
