from typing import Literal

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

type Js = Literal["js"]
type Cs = Literal["cs"]
type CodeLanguage = Js | Cs


class Code[L: CodeLanguage]:
    def __init__(self, language: L, content: str | bytes | None, file_path: str | None, start_line: int | None):
        self.language = language
        if isinstance(content, bytes):
            self.text = content.decode(errors="ignore")
        else:
            self.text = content
        self.file_path = file_path
        self.start_line = start_line

    @staticmethod
    def cs(content: str | bytes | None, file_path: str | None, start_line: int | None):
        return Code("cs", content, file_path, start_line)

    @staticmethod
    def js(content: str | bytes | None, file_path: str | None, start_line: int | None):
        return Code("js", content, file_path, start_line)

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
