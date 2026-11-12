"""``File``: an attachment to send, exactly like ``discord.File``."""

from __future__ import annotations

import io
import os
from typing import Optional, Union

__all__ = ("File",)


class File:
    """A file to upload.

    ``fp`` may be a path, raw ``bytes``, or any binary file object. Images are compressed by
    Vector before upload unless ``compress=False``.
    """

    __slots__ = ("fp", "filename", "spoiler", "description", "compress", "_data", "_path")

    def __init__(
        self,
        fp: Union[str, bytes, os.PathLike, io.IOBase],
        filename: Optional[str] = None,
        *,
        spoiler: bool = False,
        description: Optional[str] = None,
        compress: bool = True,
    ):
        self.fp = fp
        self._data: Optional[bytes] = None
        self._path: Optional[str] = None
        if isinstance(fp, (bytes, bytearray, memoryview)):
            self._data = bytes(fp)
        elif isinstance(fp, (str, os.PathLike)):
            self._path = os.fspath(fp)
            if filename is None:
                filename = os.path.basename(self._path)
        else:
            if filename is None:
                filename = os.path.basename(getattr(fp, "name", "") or "") or None
        if filename is None:
            filename = "untitled"
        if spoiler and not filename.startswith("SPOILER_"):
            filename = "SPOILER_" + filename
        self.filename = filename
        self.spoiler = spoiler or filename.startswith("SPOILER_")
        self.description = description
        self.compress = compress

    @property
    def path(self) -> Optional[str]:
        return self._path

    def read(self) -> bytes:
        if self._data is not None:
            return self._data
        if self._path is not None:
            with open(self._path, "rb") as f:
                return f.read()
        data = self.fp.read()  # type: ignore[union-attr]
        if isinstance(data, str):
            data = data.encode()
        self._data = data
        return data

    def reset(self, seek: Union[int, bool] = True) -> None:
        if hasattr(self.fp, "seek") and seek:
            self.fp.seek(0)  # type: ignore[union-attr]

    def close(self) -> None:
        if hasattr(self.fp, "close") and not isinstance(self.fp, (str, bytes, os.PathLike)):
            self.fp.close()  # type: ignore[union-attr]

    def __repr__(self) -> str:
        return f"<File filename={self.filename!r}>"
