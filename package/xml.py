from __future__ import annotations
import random, string, re
from functools import cached_property
from typing import cast, overload, Any
from lxml import etree
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from package.html import file_name_html
from package.iter import IterContainer

parser = etree.XMLParser(remove_blank_text=True)

# lxml raises an exception if you try to query a missing namespace
default_ns_map = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "altinn": "http://altinn.no/process",
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "bpmn2": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "modeler": "http://camunda.org/schema/modeler/1.0",
    "camunda": "http://camunda.org/schema/1.0/bpmn",
    "xacml": "urn:oasis:names:tc:xacml:3.0:core:schema:wd-17",
    "xsl": "http://www.w3.org/2001/XMLSchema-instance",
    "re": "http://exslt.org/regular-expressions",  # Allows the use of re:test, re:match, and re:replace functions
}


class Xml[X = etree._Element]:
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

    @property
    def lines(self):
        if not isinstance(self.element, etree._Element) or self.text is None:
            return None
        start = self.element.sourceline
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

        if isinstance(self.element, etree._Element):
            return strip_ns_declarations(etree.tostring(self.element, encoding=str, pretty_print=True, with_tail=False))

        return str(self.element)

    @cached_property
    def nsmap(self):
        if not hasattr(self.element, "nsmap"):
            return default_ns_map

        return {**default_ns_map, **self.element.nsmap}  # type: ignore

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
        if isinstance(obj, Xml):
            return obj.element
        return obj

    def __eq__(self, other: object | Xml):
        other_element = Xml.get_value(other)
        return self.element == other_element

    def __gt__(self, other: object | Xml):
        other_element = Xml.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element > other_element  # type: ignore

    def __lt__(self, other: object | Xml):
        other_element = Xml.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element < other_element  # type: ignore

    def __gte__(self, other: object | Xml):
        other_element = Xml.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element >= other_element  # type: ignore

    def __lte__(self, other: object | Xml):
        other_element = Xml.get_value(other)
        if not self.exists or other_element is None:
            return False
        return self.element <= other_element  # type: ignore

    def xpath(self, query: str) -> IterContainer[Xml[Any]]:
        if not isinstance(self.element, etree._Element):
            return IterContainer()

        res = self.element.xpath(query, namespaces=self.nsmap)

        return IterContainer(res if isinstance(res, list) else [res]).map(
            lambda element: Xml(element, self.file_path, self.remote_url)
        )

    @overload
    def __getitem__(self, key: str) -> Xml | None: ...
    @overload
    def __getitem__(self, key: tuple[str, int]) -> Xml: ...
    @overload
    def __getitem__(self, key: tuple[str, slice]) -> IterContainer[Xml]: ...
    def __getitem__(self, key: str | tuple[str, int] | tuple[str, slice]):
        if isinstance(key, str):
            return self.xpath(key).first
        (query, slice_key) = key
        return self.xpath(query)[slice_key]

def strip_ns_declarations(xml_str: str):
    return re.sub(r'\s(xmlns:[\w\d_\-.]+|targetNamespace)="[^"]*"', "", xml_str)



class ProcessTask(Xml):
    def __init__(self, xml: etree._Element | None = None, file_path: str | None = None, remote_url: str | None = None):
        super().__init__(xml, file_path, remote_url)

    @cached_property
    def type(self):
        # Checks for <altinn:taskType>...</altinn:taskType> element and altinn:taskType="..." attribute
        value = self.xpath(".//altinn:taskType/text() | ./@altinn:tasktype").first
        if value is not None:
            return str(value)

    @cached_property
    def id(self):
        value = self.xpath("./@id").first
        if value is not None:
            return str(value)


class Process(Xml):
    def __init__(self, xml: bytes | None = None, file_path: str | None = None, remote_url: str | None = None):
        super().__init__(xml, file_path, remote_url)

    @cached_property
    def tasks(self):
        return self.xpath(".//bpmn:task | .//bpmn2:task").map(
            lambda x: ProcessTask(cast(etree._Element, x.element), x.file_path, x.remote_url)
        )
