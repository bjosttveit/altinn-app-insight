from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable, Literal, cast, overload, Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

import jq
import rapidjson

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


class Json[J = object]:
    def __init__(self, json: bytes | J | None = None, file_path: str | None = None, remote_url: str | None = None):
        if isinstance(json, bytes):
            self.json = cast(J, parse_json(json))
        else:
            self.json = cast(J | None, json)
        self.file_path = file_path
        self.remote_url = remote_url

    @property
    def file_name(self):
        if self.file_path is not None:
            return Path(self.file_path).name

    @property
    def exists(self):
        return self.json is not None

    def __iter__(self):
        if isinstance(self.json, Iterable):
            for v in self.json:
                yield Json(v, file_path=self.file_path, remote_url=self.remote_url)
        else:
            raise TypeError(f"'{type(self.json)}' object is not iterable")

    def __repr__(self):
        if self._repr_inline_():
            return str(self.json)
        return json.dumps(self.json, indent=4)

    def _repr_inline_(self) -> bool:
        return not (isinstance(self.json, list) or isinstance(self.json, dict))

    def _repr_html_(self):
        lexer = get_lexer_by_name("json")
        title_settings = (
            {
                "filename": f'<a href="{self.remote_url}" target="_blank" style="color: var(--jp-content-link-color);">{self.file_path}</a>'
            }
            if self.file_path is not None
            else {}
        )
        settings = {"wrapcode": True, **title_settings}
        fmt = HtmlFormatter(**settings)
        style = "<style>{}</style>".format(fmt.get_style_defs(".output_html"))
        return style + highlight(json.dumps(self.json, indent=4), lexer, fmt)

    @staticmethod
    def to_string(value: str | Json | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value.json, str):
            return value.json

    @staticmethod
    def get_value(obj: Any):
        if isinstance(obj, Json):
            return obj.json
        return obj

    def __eq__(self, other: object | Json):
        other_json = Json.get_value(other)
        return self.json == other_json

    def __gt__(self, other: object | Json):
        other_json = Json.get_value(other)
        if not self.exists or other_json is None:
            return False
        return self.json > other_json  # type: ignore

    def __lt__(self, other: object | Json):
        other_json = Json.get_value(other)
        if not self.exists or other_json is None:
            return False
        return self.json < other_json  # type: ignore

    def __gte__(self, other: object | Json):
        other_json = Json.get_value(other)
        if not self.exists or other_json is None:
            return False
        return self.json >= other_json  # type: ignore

    def __lte__(self, other: object | Json):
        other_json = Json.get_value(other)
        if not self.exists or other_json is None:
            return False
        return self.json <= other_json  # type: ignore

    def jq(self, query: str) -> IterContainer[Json]:
        if not self.exists:
            return IterContainer()
        return IterContainer(iter(jq.compile(query).input_value(self.json))).map(
            lambda json: Json(json, self.file_path, self.remote_url)
        )

    @overload
    def __getitem__(self, key: str) -> Json | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int]) -> Json: ...
    @overload
    def __getitem__(self, key: tuple[str, slice]) -> IterContainer[Json]: ...
    def __getitem__(self, key: str | tuple[str, int] | tuple[str, slice]):
        if isinstance(key, str):
            return self.jq(key).first
        (query, slice_key) = key
        return self.jq(query)[slice_key]


class Appsettings(Json):
    type Environment = Literal["Production", "Development", "Staging", "default"]

    @staticmethod
    def env_from_path(file_path: str | None) -> Environment | None:
        if file_path is None:
            return None

        match = re.search(r"appsettings(\.([^.]+))?\.json$", file_path)
        if match is None:
            return None

        group = match.group(2)
        return cast(Appsettings.Environment, group) if group is not None else "default"

    def __init__(self, json: bytes | object | None, file_path: str | None, remote_url: str | None = None):
        super().__init__(json, file_path, remote_url)
        self.environment: Appsettings.Environment | None = Appsettings.env_from_path(file_path)


class TextResource(Json):

    @staticmethod
    def lang_from_path(file_path: str | None) -> str | None:
        if file_path is None:
            return None

        match = re.search(r"resource\.([a-z]{2})\.json$", file_path)
        if match is None:
            return None

        return match.group(1)

    def __init__(self, json: bytes | object | None, file_path: str | None, remote_url: str | None = None):
        super().__init__(json, file_path, remote_url)
        self.language = TextResource.lang_from_path(file_path)
