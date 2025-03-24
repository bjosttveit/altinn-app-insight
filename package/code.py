from __future__ import annotations
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


class Code[L: CodeLanguage]:
    def __init__(self, language: L, content: str | bytes | None, file_path: str | None, start_line: int):
        self.language = language
        if isinstance(content, bytes):
            self.text = content.decode(errors="ignore")
            self.bytes = content
        else:
            self.text = content
            self.bytes = content.encode() if content is not None else None

        self.file_path = file_path

        if self.text is not None:
            self.start_line = start_line
        else:
            self.start_line = None

    def __hash__(self):
        return hash((self.file_path, self.text, self.start_line))

    @staticmethod
    def cs(content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1) -> Code[Cs]:
        return Code("cs", content, file_path, start_line)

    @staticmethod
    def js(content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1) -> Code[Js]:
        return Code("js", content, file_path, start_line)

    @staticmethod
    def html(content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1) -> Code[Html]:
        return Code("html", content, file_path, start_line)

    @staticmethod
    def xml(content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1) -> Code[Xml]:
        return Code("xml", content, file_path, start_line)

    @property
    def exists(self):
        return self.text is not None

    def __repr__(self):
        return str(self.text)

    def _repr_html_(self) -> str:
        lexer = get_lexer_by_name(self.language)
        title_settings = {"filename": self.file_path} if self.file_path is not None else {}
        line_settings = {"linenos": "inline", "linenostart": self.start_line} if self.start_line is not None else {}
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
