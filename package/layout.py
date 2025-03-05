from __future__ import annotations

from typing import Iterable, NotRequired, TypedDict, TypeVar

import jq
import rapidjson

from .iter import IterContainer

T = TypeVar("T", str, int, float, bool, None)
type ExpressionOr[T] = T | tuple[str, *tuple[ExpressionOr, ...]]


class ComponentJson(TypedDict):
    """Can have additional properties"""

    id: str
    type: str
    hidden: NotRequired[ExpressionOr[bool]]


class LayoutDataJson(TypedDict):
    hidden: NotRequired[ExpressionOr[bool]]
    layout: list[ComponentJson]


LayoutJson = TypedDict("LayoutJson", {"$schema": str, "data": LayoutDataJson})


class Component:
    def __init__(self, component_json: ComponentJson):
        self.component_json = component_json

    @property
    def id(self) -> str:
        return self.component_json["id"]

    @property
    def type(self) -> str:
        return self.component_json["type"]

    @property
    def can_be_hidden(self) -> bool:
        hidden_prop = self.component_json.get("hidden")
        return type(hidden_prop) == list or hidden_prop == True

    def jq(self, query: str) -> IterContainer[object]:
        iterable: Iterable[object] = iter(jq.compile(query).input_value(self.component_json))
        return IterContainer(iterable)


class Layout:
    def __init__(self, layout_json: LayoutJson):
        self.layout_json = layout_json
        self.components = IterContainer(map(lambda component_json: Component(component_json), self.layout_json["data"]["layout"]))

    @staticmethod
    def from_bytes(data: bytes) -> Layout | None:
        # Ignore empty JSON files
        if len(data) == 0:
            return None

        # RapidJSON only supports regular utf-8, remove BOM if it exists
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]

        try:
            # Use RapidJSON to allow trailing commas and comments, it is unfortunately not really any faster
            layout_json: LayoutJson = rapidjson.loads(data, parse_mode=rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS)
            return Layout(layout_json)
        except:
            pass

    @property
    def schema(self):
        return self.layout_json["$schema"]

    @property
    def can_be_hidden(self):
        hidden_prop = self.layout_json.get("hidden")
        return type(hidden_prop) == list or hidden_prop == True
