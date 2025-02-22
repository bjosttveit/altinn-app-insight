from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, overload

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

from functools import cached_property, reduce
from itertools import compress, groupby, islice, starmap, tee
from typing import Generic, Iterable, Iterator, TypeVar

T = TypeVar("T")


class IterController(Generic[T]):
    def __init__(self, iterable: Iterable[T], executor: ThreadPoolExecutor):
        self.__iterable = iterable
        self.executor = executor

    def __get_iter(self, n: int = 1) -> tuple[Iterator[T], ...]:
        tup = tee(self.__iterable, n + 1)
        self.__iterable = tup[0]
        return tup[1:]

    @cached_property
    def list(self) -> list[T]:
        (iterator,) = self.__get_iter()
        return list(iterator)

    @cached_property
    def length(self) -> int:
        return len(self.list)

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
    def __getitem__(self, key: slice) -> IterController[T]: ...
    def __getitem__(self, key: int | slice) -> T | IterController[T]:
        (iterator,) = self.__get_iter()
        if isinstance(key, slice):
            return IterController(islice(iterator, key.start, key.stop, key.step), self.executor)
        return next(islice(iterator, key, None))

    def __len__(self):
        return self.length

    def __sorted(self, i: Iterable[T], key: Callable[[T], SupportsRichComparison], reverse=False):
        """Key mapping uses ThreadPoolExecutor and sorting does not happen until generator starts being consumed"""
        k, v = tee(i)
        for k, v in sorted(zip(self.executor.map(key, k), v), key=lambda k_v: k_v[0], reverse=reverse):
            yield v

    R = TypeVar("R")

    def map[R](self, func: Callable[[T], R]) -> IterController[R]:
        (a,) = self.__get_iter()
        return IterController(self.executor.map(func, a), self.executor)

    def filter(self, func: Callable[[T], bool]) -> IterController[T]:
        a, b = self.__get_iter(2)
        return IterController(compress(a, self.executor.map(func, b)), self.executor)

    def sort(self, func: Callable[[T], SupportsRichComparison], reverse=False) -> IterController[T]:
        (a,) = self.__get_iter()
        return IterController(self.__sorted(a, func, reverse), self.executor)

    def reduce(self, func: Callable[[T, T], T]) -> T | None:
        if self.is_empty:
            return None
        (a,) = self.__get_iter()
        return reduce(func, a)

    K = TypeVar("K")

    def group_by[K, R](self, key_func: Callable[[T], K], map_func: Callable[[K, IterController[T]], R]) -> IterController[R]:
        (a,) = self.__get_iter()
        s = self.__sorted(a, key_func)  # type: ignore how can I define a generic type which "extends" SupportsRichComparison?
        g = groupby(s, key=key_func)  # This does not use the ThreadPoolExecutor, but the sort does and so the values should be cached?
        return IterController(starmap(lambda k, l: map_func(k, IterController(list(l), self.executor)), g), self.executor)
