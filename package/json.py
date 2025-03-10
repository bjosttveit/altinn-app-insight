from __future__ import annotations

from typing import Iterable, NotRequired, TypedDict, TypeVar, overload

import jq
import rapidjson

from .iter import IterContainer

T = TypeVar("T", str, int, float, bool, None)
type ExpressionOr[T] = T | tuple[str, *tuple[ExpressionOr, ...]]

J = TypeVar("J")


def parse(data: bytes | None):
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
        return str(self.json)

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
            return IterContainer([])
        iterable: Iterable[object] = iter(jq.compile(query).input_value(self.json))
        json_iterable = map(lambda json: GenericJson(json), iterable)
        return IterContainer(json_iterable)

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


class GenericJsonFile(GenericJson[J]):
    def __init__(self, json: J | None, file_path: str | None):
        super().__init__(json)
        self.file_path = file_path

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return GenericJsonFile(parse(data), file_path)

    @property
    def schema(self):
        return self[".$schema"]


class ComponentJson(TypedDict):
    """Can have additional properties"""

    id: str
    type: str
    hidden: NotRequired[ExpressionOr[bool]]


class LayoutDataJson(TypedDict):
    hidden: NotRequired[ExpressionOr[bool]]
    layout: list[ComponentJson]


class LayoutJson(TypedDict):
    data: LayoutDataJson


class Component(GenericJson[ComponentJson]):
    def __init__(self, json: ComponentJson | None, layout: Layout):
        super().__init__(json)
        self.layout = layout

    @property
    def id(self):
        if self.json is None:
            return None
        return self.json["id"]

    @property
    def type(self):
        if self.json is None:
            return None
        return self.json["type"]


class Layout(GenericJsonFile[LayoutJson]):
    def __init__(self, json: LayoutJson | None, file_path: str | None):
        super().__init__(json, file_path)
        self.components = IterContainer(
            map(lambda component_json: Component(component_json, self), json["data"]["layout"] if json is not None else [])
        )

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return Layout(parse(data), file_path)
