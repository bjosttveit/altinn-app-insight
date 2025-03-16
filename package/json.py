from __future__ import annotations

import json
import re
from typing import Iterable, Literal, cast, overload

import jq
import rapidjson
from IPython.display import Code as CodeDisplay

from .iter import IterContainer


def parse_json(data: bytes | None):
    # Ignore empty JSON files
    if data is None or len(data) == 0:
        return None

    # RapidJSON only supports regular utf-8, remove BOM if it exists
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]

    try:
        # Use RapidJSON to allow trailing commas and comments, it is unfortunately not really any faster
        return rapidjson.loads(data, parse_mode=rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS)
    except:
        pass


class GenericJson[J]:
    def __init__(self, json: J | None):
        self.json = json

    @property
    def exists(self):
        return self.json is not None

    def __repr__(self):
        if isinstance(self.json, dict) or isinstance(self.json, list):
            return json.dumps(self.json, indent=4)
        return str(self.json)

    def _repr_html_(self):
        return CodeDisplay(json.dumps(self.json, indent=4), language="json")._repr_html_()

    def __eq__(self, other: object | GenericJson):
        other_json = other.json if isinstance(other, GenericJson) else other
        return self.json == other_json

    def __gt__(self, other: object | GenericJson):
        other_json = other.json if isinstance(other, GenericJson) else other
        if not self.exists or other_json is None:
            return False
        return self.json > other_json  # type: ignore

    def __lt__(self, other: object | GenericJson):
        other_json = other.json if isinstance(other, GenericJson) else other
        if not self.exists or other_json is None:
            return False
        return self.json < other_json  # type: ignore

    def __gte__(self, other: object | GenericJson):
        other_json = other.json if isinstance(other, GenericJson) else other
        if not self.exists or other_json is None:
            return False
        return self.json >= other_json  # type: ignore

    def __lte__(self, other: object | GenericJson):
        other_json = other.json if isinstance(other, GenericJson) else other
        if not self.exists or other_json is None:
            return False
        return self.json <= other_json  # type: ignore

    def jq(self, query: str) -> IterContainer[GenericJson[object]]:
        if not self.exists:
            return IterContainer()
        return IterContainer(iter(jq.compile(query).input_value(self.json))).map(lambda json: GenericJson(json))

    @overload
    def __getitem__(self, key: str) -> GenericJson[object] | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int]) -> GenericJson[object]: ...
    @overload
    def __getitem__(self, key: tuple[str, slice]) -> IterContainer[GenericJson[object]]: ...
    def __getitem__(self, key: str | tuple[str, int] | tuple[str, slice]):
        if isinstance(key, str):
            return self.jq(key).first
        (query, slice_key) = key
        return self.jq(query)[slice_key]


class GenericJsonFile[J](GenericJson[J]):
    def __init__(self, json: J | None, file_path: str | None):
        super().__init__(json)
        self.file_path = file_path

    @staticmethod
    def empty():
        return GenericJsonFile(None, None)

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return GenericJsonFile(parse_json(data), file_path)

    @property
    def schema(self):
        return self[".$schema"]


class AppsettingsJsonFile[J](GenericJsonFile[J]):
    type Environment = Literal["Production", "Development", "Staging", "default"]

    @staticmethod
    def env_from_path(file_path: str | None) -> Environment | None:
        if file_path is None:
            return None

        match = re.search(r"appsettings(\.([^.]+))?\.json$", file_path)
        if match is None:
            return None

        group = match.group(2)
        return cast(AppsettingsJsonFile.Environment, group) if group is not None else "default"

    def __init__(self, json: J | None, file_path: str | None):
        super().__init__(json, file_path)
        self.environment: AppsettingsJsonFile.Environment | None = AppsettingsJsonFile.env_from_path(file_path)

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return AppsettingsJsonFile(parse_json(data), file_path)
