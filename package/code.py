from typing import Literal

from IPython.display import Code as CodeDisplay

type Js = Literal["js"]
type Cs = Literal["cs"]
type CodeLanguage = Js | Cs


class Code[L: CodeLanguage]:
    def __init__(self, language: L, content: str | bytes | None, file_path: str | None):
        self.language = language
        if isinstance(content, bytes):
            self.text = content.decode(errors="ignore")
        else:
            self.text = content
        self.file_path = file_path

    @staticmethod
    def cs(content: str | bytes | None, file_path: str | None):
        return Code("cs", content, file_path)

    @staticmethod
    def js(content: str | bytes | None, file_path: str | None):
        return Code("js", content, file_path)

    @property
    def exists(self):
        return self.text is not None

    def __repr__(self):
        return str(self.text)

    def _repr_html_(self):
        return CodeDisplay(data=self.text, language=self.language)._repr_html_()
