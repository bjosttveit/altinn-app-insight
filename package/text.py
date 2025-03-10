from __future__ import annotations

import re
from types import EllipsisType
from typing import overload

from package.iter import IterContainer


class TextFile:
    def __init__(self, text: str | None, file_path: str | None):
        self.text = text
        self.file_path = file_path

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        if data is None:
            return TextFile(None, file_path)
        text = data.decode(errors="ignore")
        if len(text) == 0:
            return TextFile(None, file_path)
        return TextFile(text, file_path)

    @property
    def exists(self):
        return self.text is not None

    def __repr__(self):
        return str(self.text)

    def __eq__(self, other: object | TextFile):
        other_text = other.text if isinstance(other, TextFile) else other
        return self.text == other_text

    def __gt__(self, other: object | TextFile):
        other_json = other.text if isinstance(other, TextFile) else other
        if not self.exists or other_json is None:
            return False
        return self.text > other_json  # type: ignore

    def __lt__(self, other: object | TextFile):
        other_json = other.text if isinstance(other, TextFile) else other
        if not self.exists or other_json is None:
            return False
        return self.text < other_json  # type: ignore

    def __gte__(self, other: object | TextFile):
        other_json = other.text if isinstance(other, TextFile) else other
        if not self.exists or other_json is None:
            return False
        return self.text >= other_json  # type: ignore

    def __lte__(self, other: object | TextFile):
        other_json = other.text if isinstance(other, TextFile) else other
        if not self.exists or other_json is None:
            return False
        return self.text <= other_json  # type: ignore

    def __matches(self, pattern: str, group: int = 0):
        if self.text is None:
            return
        for match in re.finditer(pattern, self.text):
            yield match.group(group)

    def find_all(self, pattern: str, group: int = 0):
        return IterContainer(self.__matches(pattern, group))

    @overload
    def __getitem__(self, key: str) -> str | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int]) -> str | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int | EllipsisType, int]) -> str: ...
    @overload
    def __getitem__(self, key: tuple[str, int | EllipsisType, slice]) -> IterContainer[str]: ...
    def __getitem__(self, key: str | tuple[str, int] | tuple[str, int | EllipsisType, int] | tuple[str, int | EllipsisType, slice]):
        if isinstance(key, str):
            return self.find_all(key).first
        if len(key) == 2:
            (pattern, group) = key
            return self.find_all(pattern, group).first
        (pattern, group, slice_key) = key
        return self.find_all(pattern, group if isinstance(group, int) else 0)[slice_key]
