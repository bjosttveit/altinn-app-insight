from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable, TypeVar

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison


S = TypeVar("S")


def lazy_sorted(i: Iterable[S], key: Callable[[S], SupportsRichComparison], reverse=False):
    """Sorting does not occur until the generator starts being consumed"""
    for s in sorted(i, key=key, reverse=reverse):
        yield s
