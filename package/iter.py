from __future__ import annotations

from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, overload

from .html import html

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

from functools import cached_property, reduce
from itertools import compress, groupby, islice, starmap, tee
from typing import Iterable, Iterator, TypeVar


class IterContainer[T]:
    def __init__(self, iterable: Iterable[T] | None = None, executor: ThreadPoolExecutor | None = None):
        self.__iterable: Iterable[T] = iterable if iterable is not None else []
        self.executor = executor

    def __repr__(self):
        return "[" + ", ".join(map(lambda i: str(i), self.list)) + "]"

    def _repr_html_(self):
        return html(self.list)

    def with_iterable[R](self, iterable: Iterable[R]) -> IterContainer[R]:
        return IterContainer(iterable, self.executor)

    def __map[P, R](self, func: Callable[[P], R], iterable: Iterable[P]) -> Iterable[R]:
        if self.executor is not None:
            return self.executor.map(func, iterable)
        return map(func, iterable)

    def __get_iter(self, n: int = 1) -> tuple[Iterator[T], ...]:
        tup = tee(self.__iterable, n + 1)
        self.__iterable = tup[0]
        return tup[1:]

    @cached_property
    def list(self) -> list[T]:
        (iterator,) = self.__get_iter()
        return list(iterator)

    @cached_property
    def first(self) -> T | None:
        (t,) = self.__get_iter()
        try:
            return next(t)
        except StopIteration:
            return None

    def first_or_default(self, default: T) -> T:
        (t,) = self.__get_iter()
        try:
            return next(t)
        except StopIteration:
            return default

    @cached_property
    def length(self) -> int:
        return len(self.list)

    @property
    def is_not_empty(self) -> bool:
        return not self.is_empty

    @cached_property
    def is_empty(self) -> bool:
        (t,) = self.__get_iter()
        try:
            next(t)
            return False
        except StopIteration:
            return True

    @overload
    def __getitem__(self, key: int) -> T: ...
    @overload
    def __getitem__(self, key: slice) -> IterContainer[T]: ...
    def __getitem__(self, key: int | slice) -> T | IterContainer[T]:
        (iterator,) = self.__get_iter()
        if isinstance(key, slice):
            return IterContainer(islice(iterator, key.start, key.stop, key.step), self.executor)
        return next(islice(iterator, key, None))

    def __len__(self):
        return self.length

    def __sorted(self, i: Iterable[T], key: Callable[[T], SupportsRichComparison] | None = None, reverse=False):
        """Key mapping uses ThreadPoolExecutor and sorting does not happen until generator starts being consumed"""
        func = key if key is not None else lambda t: t
        k, v = tee(i)
        for k, v in sorted(zip(self.__map(func, k), v), key=lambda k_v: k_v[0], reverse=reverse):
            yield v

    def __unique(self, i: Iterable[T], key: Callable[[T], object] | None):
        k, v = tee(i)
        seenset = set()
        seenlist = []
        for k, v in zip(self.__map(key, k) if key is not None else k, v):
            try:
                if k not in seenset:
                    seenset.add(k)
                    yield v
            except TypeError:
                if k not in seenlist:
                    seenlist.append(k)
                    yield v

    def map[R](self, func: Callable[[T], R]) -> IterContainer[R]:
        (a,) = self.__get_iter()
        return self.with_iterable(self.__map(func, a))

    def starmap[*Ts, R](self: IterContainer[tuple[*Ts]], func: Callable[[*Ts], R]) -> IterContainer[R]:
        (a,) = self.__get_iter()
        return self.with_iterable(starmap(func, a))

    def flat_map[R](self, func: Callable[[T], IterContainer[R] | Iterable[R] | None]) -> IterContainer[R]:
        (a,) = self.__get_iter()
        return self.with_iterable(
            (c for b in self.__map(func, a) if b is not None for c in (b.__iterable if isinstance(b, IterContainer) else b))
        )

    def filter(self, func: Callable[[T], bool]) -> IterContainer[T]:
        a, b = self.__get_iter(2)
        return self.with_iterable(compress(a, self.__map(func, b)))

    def sort(self, func: Callable[[T], SupportsRichComparison] | None = None, reverse=False) -> IterContainer[T]:
        (a,) = self.__get_iter()
        return self.with_iterable(self.__sorted(a, func, reverse))

    def reduce(self, func: Callable[[T, T], T]) -> T | None:
        if self.is_empty:
            return None
        (a,) = self.__get_iter()
        return reduce(func, a)

    def some(self, func: Callable[[T], bool]) -> bool:
        if self.is_empty:
            return False
        (a,) = self.__get_iter()
        for v in a:
            if func(v):
                return True
        return False

    def every(self, func: Callable[[T], bool]) -> bool:
        if self.is_empty:
            return True
        (a,) = self.__get_iter()
        for v in a:
            if not func(v):
                return False
        return True

    def unique(self, key: Callable[[T], object] | None = None) -> IterContainer[T]:
        (a,) = self.__get_iter()
        return self.with_iterable(self.__unique(a, key))

    K = TypeVar("K")

    def group_by[K, R](
        self, key_func: Callable[[T], K], map_func: Callable[[K, IterContainer[T]], R]
    ) -> IterContainer[R]:
        (a,) = self.__get_iter()
        s = self.__sorted(a, key_func)  # type: ignore how can I define a generic type which "extends" SupportsRichComparison?
        g = groupby(
            s, key=key_func
        )  # This does not use the ThreadPoolExecutor, but the sort does and so the values should be cached?
        return self.with_iterable(starmap(lambda k, l: map_func(k, self.with_iterable(list(l))), g))


class IterController[T](ABC):
    def __init__(self, iterable: IterContainer[T]):
        self.i = iterable

    @property
    def list(self) -> list[T]:
        return self.i.list

    @property
    def length(self):
        return self.i.length

    @property
    def is_empty(self):
        return self.i.is_empty

    def __len__(self):
        return self.length

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self.i.executor is not None:
            self.i.executor.shutdown()
