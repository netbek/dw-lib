from pydantic.main import IncEx
from typing import Any

import datetime
import pydash


class BaseMixin:
    def model_dump_copy(
        self,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        by_alias: bool | None = False,
        update: dict[str, Any] | None = None,
    ):
        data = self.model_dump(by_alias=by_alias, include=include, exclude=exclude)

        if update:
            data.update(update)

        return data


class PeerDBFactoryMixin:
    @classmethod
    def peerdb_version(cls) -> int:
        return int(pydash.unique_id())

    @classmethod
    def peerdb_is_deleted(cls) -> int:
        return 0

    @classmethod
    def peerdb_synced_at(cls) -> datetime.datetime:
        return datetime.datetime.now()
