import random
import string
from html import escape as html_escape
from typing import Iterable

from tabulate import JupyterHTMLStr, tabulate


def is_html(obj: object):
    return callable(getattr(obj, "_repr_html_", None))


def contains_html(seq: list | tuple):
    for e in seq:
        if is_html(e):
            return True
        if (isinstance(e, list) or isinstance(e, tuple)) and contains_html(e):
            return True
    return False


def html(obj: object) -> str:
    if is_html(obj):
        return obj._repr_html_()  # type: ignore
    if isinstance(obj, list) or isinstance(obj, tuple):
        if contains_html(obj):
            return (
                '<div style="padding-left: 10px; border-left: 2px solid var(--jp-border-color1);">'
                + "<br>".join(map(lambda i: html(i), obj))
                + "</div><br>"
            )
        return "[" + ", ".join(map(lambda i: html_escape(str(i)), obj)) + "]"
    return html_escape(str(obj))


def tabulate_html(_data: Iterable[Iterable[object]], headers: list[str]) -> JupyterHTMLStr:
    data = [[html(value) for value in values] for values in _data]

    className = "".join(random.choices(string.ascii_letters, k=16))
    return JupyterHTMLStr(
        f"""
        <style>
            .{className} pre {{
                text-align: left;
            }}
            .{className} td {{
                vertical-align: top !important;
            }}
        </style>
        <div class="{className}">
        """
        + tabulate(data, headers=headers, tablefmt="unsafehtml")
        + "</div>"
    )
