from __future__ import annotations
import random, string
from functools import cache, cached_property
from typing import overload, Any

from lxml import html
from lxml.etree import _Element
from elementpath import Selector
from elementpath.xpath3 import XPath3Parser
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from package.html_output import file_name_html
from package.iter import IterContainer

parser = html.HTMLParser(remove_blank_text=True)


class Html[X = _Element]:
    def __init__(self, element: bytes | X | None = None, file_path: str | None = None, remote_url: str | None = None):
        if isinstance(element, bytes):
            self.element = html.fromstring(element, parser=parser)
        else:
            self.element = element
        self.file_path = file_path
        self.remote_url = remote_url

    @property
    def file_name(self):
        if self.file_path is not None:
            return Path(self.file_path).name

    @property
    def lines(self):
        if not isinstance(self.element, _Element) or self.text is None:
            return None
        if (start := self.element.sourceline) is None:
            return None
        end = start + len(self.text.splitlines()) - 1
        return [self.element.sourceline, end]

    @property
    def remote_url_lines(self):
        if self.lines is None:
            return self.remote_url
        return f"{self.remote_url}#L{self.lines[0]}-L{self.lines[1]}"

    @cached_property
    def text(self):
        if self.element is None:
            return None

        if isinstance(self.element, _Element):
            return html.tostring(self.element, encoding=str, pretty_print=True, with_tail=False)

        return str(self.element)

    @property
    def exists(self):
        return self.text is not None

    def __repr__(self):
        return str(self.text)

    def _repr_inline_(self) -> bool:
        return not (isinstance(self.element, _Element))

    def _repr_html_(self):
        lexer = get_lexer_by_name("html")
        title_settings = (
            {"filename": file_name_html(self.file_path, self.remote_url_lines)} if self.file_path is not None else {}
        )
        line_settings = {"linenos": "inline", "linenostart": self.lines[0]} if self.lines is not None else {}
        class_name = "".join(random.choices(string.ascii_letters, k=16))
        settings = {"wrapcode": True, "style": "monokai", "cssclass": class_name, **title_settings, **line_settings}
        fmt = HtmlFormatter(**settings)
        style = "<style>{}</style>".format(fmt.get_style_defs())
        return style + highlight(self.text, lexer, fmt)

    @staticmethod
    def get_value(obj: Any):
        if isinstance(obj, Html):
            return obj.element
        return obj

    def __eq__(self, other: object | Html):
        other_element = Html.get_value(other)
        return self.element == other_element

    def __gt__(self, other: object | Html):
        other_element = Html.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element > other_element  # type: ignore

    def __lt__(self, other: object | Html):
        other_element = Html.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element < other_element  # type: ignore

    def __gte__(self, other: object | Html):
        other_element = Html.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element >= other_element  # type: ignore

    def __lte__(self, other: object | Html):
        other_element = Html.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element <= other_element  # type: ignore

    @cache
    @staticmethod
    def make_selector(query: str) -> Selector:
        return Selector(query, parser=XPath3Parser)

    def xpath(self, query: str) -> IterContainer[Html[Any]]:
        if not isinstance(self.element, _Element):
            return IterContainer()

        res = Html.make_selector(query).select(self.element)

        return IterContainer(res if isinstance(res, list) else [res]).map(
            lambda element: Html(element, self.file_path, self.remote_url)
        )

    @overload
    def __getitem__(self, key: str) -> Html | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int]) -> Html: ...
    @overload
    def __getitem__(self, key: tuple[str, slice]) -> IterContainer[Html]: ...
    def __getitem__(self, key: str | tuple[str, int] | tuple[str, slice]):
        if isinstance(key, str):
            return self.xpath(key).first
        (query, slice_key) = key
        return self.xpath(query)[slice_key]
