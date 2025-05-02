from __future__ import annotations
from functools import cached_property
from typing import overload, Any
from lxml import etree
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from package.iter import IterContainer

parser = etree.XMLParser(remove_blank_text=True)


class XML[X = etree._Element]:
    def __init__(self, xml: bytes | X | None = None, file_path: str | None = None, remote_url: str | None = None):
        if isinstance(xml, bytes):
            self.element = etree.fromstring(xml, parser=parser)
        else:
            self.element = xml
        self.file_path = file_path
        self.remote_url = remote_url

    @property
    def file_name(self):
        if self.file_path is not None:
            return Path(self.file_path).name

    @cached_property
    def text(self):
        if self.element is None:
            return None

        if isinstance(self.element, etree._Element):
            return etree.tostring(self.element, encoding=str, pretty_print=True)

        return self.element

    @property
    def exists(self):
        return self.text is not None

    def __repr__(self):
        return str(self.text)

    def _repr_inline_(self) -> bool:
        return not (isinstance(self.element, etree._Element))

    def _repr_html_(self):
        lexer = get_lexer_by_name("xml")
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
        return style + highlight(self.text, lexer, fmt)

    @staticmethod
    def get_value(obj: Any):
        if isinstance(obj, XML):
            return obj.element
        return obj

    def __eq__(self, other: object | XML):
        other_element = XML.get_value(other)
        return self.element == other_element

    def __gt__(self, other: object | XML):
        other_element = XML.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element > other_element  # type: ignore

    def __lt__(self, other: object | XML):
        other_element = XML.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element < other_element  # type: ignore

    def __gte__(self, other: object | XML):
        other_element = XML.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element >= other_element  # type: ignore

    def __lte__(self, other: object | XML):
        other_element = XML.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element <= other_element  # type: ignore

    def xpath(self, query: str) -> IterContainer[XML[Any]]:
        if not isinstance(self.element, etree._Element):
            return IterContainer()

        res = []
        try:
            res = self.element.xpath(query, namespaces=self.element.nsmap)  # type: ignore
        except etree.XPathEvalError as e:
            # Sometimes different namespaces are used, like 'bpmn' or 'bpmn2'. I don't want a crash in that situation.
            if str(e) != "Undefined namespace prefix":
                raise

        return IterContainer(res if isinstance(res, list) else [res]).map(
            lambda element: XML(element, self.file_path, self.remote_url)
        )

    @overload
    def __getitem__(self, key: str) -> XML | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int]) -> XML: ...
    @overload
    def __getitem__(self, key: tuple[str, slice]) -> IterContainer[XML]: ...
    def __getitem__(self, key: str | tuple[str, int] | tuple[str, slice]):
        if isinstance(key, str):
            return self.xpath(key).first
        (query, slice_key) = key
        return self.xpath(query)[slice_key]
