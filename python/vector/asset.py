"""``Asset``: a remote image (avatar, banner, emoji) with discord.py's ``read()`` / ``save()``."""

from __future__ import annotations

import asyncio
import io
import os
import urllib.request
from typing import Any, Optional, Union

__all__ = ("Asset",)


class Asset:
    __slots__ = ("url", "key", "_cached_path")

    def __init__(self, url: str, *, key: Optional[str] = None, cached_path: Optional[str] = None):
        self.url = url
        self.key = key or url
        self._cached_path = cached_path or None

    def __str__(self) -> str:
        return self.url

    def __repr__(self) -> str:
        return f"<Asset url={self.url!r}>"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Asset) and other.url == self.url

    def __hash__(self) -> int:
        return hash(self.url)

    def __bool__(self) -> bool:
        return bool(self.url)

    async def read(self) -> bytes:
        if self._cached_path and os.path.exists(self._cached_path):
            with open(self._cached_path, "rb") as f:
                return f.read()

        def fetch() -> bytes:
            req = urllib.request.Request(self.url, headers={"User-Agent": "vector-sdk-py"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()

        return await asyncio.get_running_loop().run_in_executor(None, fetch)

    async def save(self, fp: Union[str, os.PathLike, io.BufferedIOBase], *, seek_begin: bool = True) -> int:
        data = await self.read()
        if isinstance(fp, io.BufferedIOBase):
            written = fp.write(data)
            if seek_begin:
                fp.seek(0)
            return written
        with open(fp, "wb") as f:
            return f.write(data)

    def with_size(self, size: int) -> "Asset":
        return self

    def with_format(self, format: str) -> "Asset":
        return self

    def replace(self, **kwargs: Any) -> "Asset":
        return self
