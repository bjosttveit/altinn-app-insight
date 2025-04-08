from __future__ import annotations
from functools import cached_property
from pathlib import Path
from typing import Literal, cast
import re

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from package.iter import IterContainer

type Js = Literal["js"]
type Cs = Literal["cs"]
type Html = Literal["html"]
type Xml = Literal["xml"]
type CodeLanguage = Js | Cs | Html | Xml
type Lines = tuple[int, int] | None


class Code[L: CodeLanguage]:
    def __init__(self, language: L, content: bytes | None, file_path: str | None, remote_url: str | None, lines: Lines):
        self.language = language
        self.bytes = content
        self.file_path = file_path
        self.remote_url = remote_url
        self.lines = lines

    @property
    def remote_url_lines(self):
        if self.lines is None:
            return self.remote_url
        return f"{self.remote_url}#L{self.lines[0]}-L{self.lines[1]}"

    @cached_property
    def text(self):
        return self.bytes.decode(errors="ignore") if self.bytes is not None else None

    @staticmethod
    def cs(
        content: bytes | None = None, file_path: str | None = None, remote_url: str | None = None, lines: Lines = None
    ) -> Code[Cs]:
        return Code("cs", content, file_path, remote_url, lines)

    @staticmethod
    def js(
        content: bytes | None = None, file_path: str | None = None, remote_url: str | None = None, lines: Lines = None
    ) -> Code[Js]:
        return Code("js", content, file_path, remote_url, lines)

    @staticmethod
    def html(
        content: bytes | None = None, file_path: str | None = None, remote_url: str | None = None, lines: Lines = None
    ) -> Code[Html]:
        return Code("html", content, file_path, remote_url, lines)

    @staticmethod
    def xml(
        content: bytes | None = None, file_path: str | None = None, remote_url: str | None = None, lines: Lines = None
    ) -> Code[Xml]:
        return Code("xml", content, file_path, remote_url, lines)

    @property
    def file_name(self):
        if self.file_path is not None:
            return Path(self.file_path).name

    @property
    def exists(self):
        return self.text is not None

    def __repr__(self):
        return str(self.text)

    def _repr_html_(self) -> str:
        lexer = get_lexer_by_name(self.language)
        title_settings = (
            {
                "filename": f'<a href="{self.remote_url_lines}" target="_blank" style="color: var(--jp-content-link-color);">{self.file_path}</a>'
            }
            if self.file_path is not None
            else {}
        )
        line_settings = {"linenos": "inline", "linenostart": self.lines[0] if self.lines is not None else 1}
        settings = {"wrapcode": True, **title_settings, **line_settings}
        fmt = HtmlFormatter(**settings)
        style = "<style>{}</style>".format(fmt.get_style_defs(".output_html"))
        return style + highlight(self.text, lexer, fmt)

    def __eq__(self, other: object | Code):
        other_text = other.text if isinstance(other, Code) else other
        return self.text == other_text

    def __gt__(self, other: object | Code):
        other_text = other.text if isinstance(other, Code) else other
        if not self.exists or other_text is None:
            return False
        return self.text > other_text  # type: ignore

    def __lt__(self, other: object | Code):
        other_text = other.text if isinstance(other, Code) else other
        if not self.exists or other_text is None:
            return False
        return self.text < other_text  # type: ignore

    def __gte__(self, other: object | Code):
        other_text = other.text if isinstance(other, Code) else other
        if not self.exists or other_text is None:
            return False
        return self.text >= other_text  # type: ignore

    def __lte__(self, other: object | Code):
        other_text = other.text if isinstance(other, Code) else other
        if not self.exists or other_text is None:
            return False
        return self.text <= other_text  # type: ignore

    def __matches(self, pattern: str, group: int = 0):
        if self.text is None:
            return
        for match in re.finditer(pattern, self.text):
            yield cast(str, match.group(group))

    def find_all(self, pattern: str, group: int = 0):
        return IterContainer(self.__matches(pattern, group))

    def find(self, pattern: str, group: int = 0):
        return self.find_all(pattern, group).first
