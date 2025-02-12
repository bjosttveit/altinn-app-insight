from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING, Generic, TypedDict

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import cached_property
from io import BufferedReader
from itertools import compress, groupby, islice, starmap, tee
from pathlib import Path
from typing import Callable, Iterable, Iterator, TypeVar, cast
from zipfile import ZipFile

from tabulate import tabulate

from package import Environment, Version, VersionLock


class App:
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path, data: dict[str, object] = {}):
        self.env: Environment = env
        self.org = org
        self.app = app
        self.__app_dir = app_dir
        self.data = data

    def __repr__(self):
        headers = ["Env", "Org", "App", *self.data_keys]
        data = [[self.env, self.org, self.app, *self.data_values]]
        return tabulate(data, headers=headers, tablefmt="simple_grid")

    def with_data(self, data: dict[str, object]) -> App:
        if self.open:
            raise Exception("Attempted to copy an `App` object while open for reading, this could cause weird issues!")
        copy = deepcopy(self)
        copy.data = data
        return copy

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.__app_dir.joinpath(self.file_name)

    __file: BufferedReader | None = None
    __zip_file: ZipFile | None = None
    __files: list[str] | None = None

    T = TypeVar("T")

    # Uses a context manager to make sure any file operations are closed
    # Does not open any files yet, this happens lazily only when needed
    @staticmethod
    def wrap_open_app(__func: Callable[[App], T]) -> Callable[[App], T]:
        def func(app: App):
            with app as open_app:
                return __func(open_app)

        return func

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.data.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return list(self.data.values())

    # Creates a copy of the App instance with the data returned in the callback
    @staticmethod
    def wrap_with_data(__func: Callable[[App], dict[str, object]]) -> Callable[[App], App]:
        def func(app: App):
            return app.with_data(__func(app))

        return func

    def __enter__(self):
        self.open = True
        return self

    def __exit__(self, type, value, traceback):
        self.open = False
        if self.__zip_file is not None:
            self.__zip_file.close()
            self.__zip_file = None
        if self.__file is not None:
            self.__file.close()
            self.__file = None

    def __ensure_open(self):
        if self.__zip_file is None:
            self.__file = open(self.file_path, "rb")
            self.__zip_file = ZipFile(self.__file)
        if self.__files is None:
            self.__files = self.__zip_file.namelist()

    @property
    def content(self) -> ZipFile:
        if not self.open:
            raise Exception("Tried to access `App.content` without first opening the file using the `with` keyword")
        self.__ensure_open()
        return cast(ZipFile, self.__zip_file)

    @property
    def files(self) -> list[str]:
        if not self.open:
            raise Exception("Tried to access `App.files` without first opening the file using the `with` keyword")
        if self.__files is None:
            self.__ensure_open()
        return cast(list[str], self.__files)

    def first_match(self, file_pattern: str, line_pattern: str) -> re.Match[str] | None:
        file_names = filter(lambda name: re.search(file_pattern, name) is not None, self.files)
        for name in file_names:
            with self.content.open(name) as zf:
                for line in zf.readlines():
                    match = re.search(line_pattern, line.decode())
                    if match is not None:
                        return match

    @cached_property
    def frontend_version(self) -> Version:
        match = self.first_match(
            r"/App/views/Home/Index.cshtml$",
            r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"',
        )
        return Version(match.group(1)) if match is not None else Version(None)

    @cached_property
    def backend_version(self) -> Version:
        match = self.first_match(
            r"/App/[^/]+.csproj$",
            r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"',
        )
        return Version(match.group(3)) if match is not None else Version(None)


class Apps:
    def __init__(self, apps: Iterable[App], executor: ThreadPoolExecutor):
        self.__apps = apps
        self.__executor = executor

    def __repr__(self):
        if self.length == 0:
            print("Count: 0")

        headers = ["Env", "Org", "App", *self.list[0].data_keys]
        data = [[app.env, app.org, app.app, *app.data_values] for app in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.__executor.shutdown()

    def __get_iter(self, n: int = 1) -> tuple[Iterator[App], ...]:
        tup = tee(self.__apps, n + 1)
        self.__apps = tup[0]
        return tup[1:]

    @cached_property
    def list(self) -> list[App]:
        (iterator,) = self.__get_iter()
        return list(iterator)

    @cached_property
    def length(self):
        return len(self.list)

    def __getitem__(self, key):
        (iterator,) = self.__get_iter()
        if isinstance(key, slice):
            return Apps(islice(iterator, key.start, key.stop, key.step), self.__executor)
        return next(islice(iterator, key, None))

    def __len__(self):
        return self.length

    @classmethod
    def init(cls, cache_dir: Path, max_open_files=100) -> Apps:
        lock_path = Path.joinpath(cache_dir, ".apps.lock.json")
        if not lock_path.exists():
            print("Failed to locate lock file")
            exit(1)

        with open(lock_path, "r") as f:
            lock_file: VersionLock = json.load(f)

        apps: list[App] = []
        for lock_data in lock_file.values():
            if lock_data["status"] == "success":
                apps.append(App(lock_data["env"], lock_data["org"], lock_data["app"], cache_dir))

        executor = ThreadPoolExecutor(max_workers=max_open_files)

        return cls(apps, executor)

    def where(self, __func: Callable[[App], bool]) -> Apps:
        a, b = self.__get_iter(2)
        func = App.wrap_open_app(__func)
        return Apps(compress(a, self.__executor.map(func, b)), self.__executor)

    def select(self, __func: Callable[[App], dict[str, object]]) -> Apps:
        (a,) = self.__get_iter()
        func = App.wrap_with_data(App.wrap_open_app(__func))
        return Apps(self.__executor.map(func, a), self.__executor)

    def order_by(self, __func: Callable[[App], SupportsRichComparison], reverse=False) -> Apps:
        (a,) = self.__get_iter()
        func = App.wrap_open_app(__func)
        return Apps(sorted(a, key=func, reverse=reverse), self.__executor)

    def group_by(self, group_func: Callable[[App], dict[str, SupportsRichComparison]]) -> GroupedApps:
        (a,) = self.__get_iter()

        def key_func(app: App) -> tuple[tuple[str, object], ...]:
            group = App.wrap_open_app(group_func)(app)
            return tuple(zip(group.keys(), group.values()))

        s = sorted(a, key=key_func)
        g = groupby(s, key=key_func)


        groups = starmap(lambda column_tuples, apps: Group(dict(column_tuples), list(apps)), g)
        return GroupedApps(groups, self.__executor)


class Group:
    type Aggregators = dict[str, Callable[[Group], object]]

    def __init__(self, groupings: dict[str, object], apps: Iterable[App], aggregators: Group.Aggregators = {}):
        self.groupings = groupings
        self.__apps = apps
        self.aggregators = aggregators

    def __repr__(self):
        headers = [*self.group_keys, *self.data_keys]
        data = [[*self.group_values, *self.data_values]]
        return tabulate(data, headers=headers, tablefmt="simple_grid")

    def with_aggregators(self, data: Group.Aggregators) -> Group:
        (a,) = self.__get_iter()
        return Group(self.groupings, a, data)

    @staticmethod
    def wrap_with_aggregators(aggregators:  Group.Aggregators) -> Callable[[Group], Group]:
        def func(group: Group):
            return group.with_aggregators(aggregators)
        return func

    def __get_iter(self, n: int = 1) -> tuple[Iterator[App], ...]:
        tup = tee(self.__apps, n + 1)
        self.__apps = tup[0]
        return tup[1:]

    @cached_property
    def group_keys(self) -> list[str]:
        return list(self.groupings.keys())

    @cached_property
    def group_values(self) -> list[object]:
        return list(self.groupings.values())

    @cached_property
    def data(self) -> dict[str, object]:
        return {name: value for name, value in zip(self.data_keys, self.data_values)}

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.aggregators.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return [func(self) for func in self.aggregators.values()]

    @cached_property
    def list(self) -> list[App]:
        (iterator,) = self.__get_iter()
        return list(iterator)

    @cached_property
    def length(self):
        return len(self.list)

    def __getitem__(self, key):
        (iterator,) = self.__get_iter()
        if isinstance(key, slice):
            return Group(self.groupings, islice(iterator, key.start, key.stop, key.step), self.aggregators)
        return next(islice(iterator, key, None))

    def __len__(self):
        return self.length


class GroupedApps:
    def __init__(self, groups: Iterable[Group], executor: ThreadPoolExecutor):
        self.__groups = groups
        self.__executor = executor

    def __repr__(self):
        if self.length == 0:
            print("Count: 0")

        headers = [*self.list[0].group_keys, *self.list[0].data_keys]
        data = [[*group.group_values, *group.data_values] for group in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.__executor.shutdown()

    def __get_iter(self, n: int = 1) -> tuple[Iterator[Group], ...]:
        tup = tee(self.__groups, n + 1)
        self.__groups = tup[0]
        return tup[1:]

    @cached_property
    def list(self) -> list[Group]:
        (iterator,) = self.__get_iter()
        return list(iterator)

    @cached_property
    def length(self):
        return len(self.list)

    def __getitem__(self, key):
        (iterator,) = self.__get_iter()
        if isinstance(key, slice):
            return GroupedApps(islice(iterator, key.start, key.stop, key.step), self.__executor)
        return next(islice(iterator, key, None))

    def __len__(self):
        return self.length

    def where(self, __func: Callable[[App], bool]) -> GroupedApps:
        raise NotImplemented
        # a, b = self.__get_iter(2)
        # func = Apps.wrap_open_app(__func)
        # return Apps(compress(a, self.__executor.map(func, b)), self.__executor)

    def order_by(self, func: Callable[[Group], SupportsRichComparison], reverse=False) -> GroupedApps:
        (a,) = self.__get_iter()
        return GroupedApps(sorted(a, key=func, reverse=reverse), self.__executor)

    def select(self, aggregators: Group.Aggregators) -> GroupedApps:
        (a,) = self.__get_iter()
        func = Group.wrap_with_aggregators(aggregators)
        return GroupedApps(self.__executor.map(func, a), self.__executor)


async def main():
    cache_dir = Path("./data")

    with Apps.init(cache_dir, max_open_files=100) as apps:

        start = time.time()

        # print(
        #     apps.where(
        #         lambda app: app.env == "tt02"
        #         and app.frontend_version >= "4.0.0"
        #         and app.frontend_version != "4"
        #         and app.frontend_version.preview is None
        #     ).select(lambda app: {"Version": app.frontend_version})
        # )

        # apps_v4 = apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version.preview is None)
        # apps_locked = apps_v4.where(lambda app: app.frontend_version != "4")
        # print(f"{apps_locked.length} / {apps_v4.length}")

        # Apps testing navigation feature
        print(
            apps.where(lambda app: app.frontend_version.preview is not None and "navigation" in app.frontend_version.preview).select(
                lambda app: {"Version": app.frontend_version}
            )
        )

        # Apps on different major versions frontend
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.exists)
            .group_by(lambda app: {"Frontend major version": cast(int, app.frontend_version.major)})
            .select({"Count": lambda group: group.length})
            .order_by(lambda group: (group.groupings["Frontend major version"],))
        )

        # Apps on different major versions backend
        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version.exists)
            .group_by(lambda app: {"Backend major version": cast(int, app.backend_version.major)})
            .select({"Count": lambda group: group.length})
            .order_by(lambda group: (group.groupings["Backend major version"],))
        )

        # Apps in prod not running latest in v4
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
            .select(lambda app: {**app.data, "Frontend version": app.frontend_version})
            .order_by(lambda app: (app.org, app.frontend_version, app.app))
        )

        # Service owners with locked app frontend per version
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
            .group_by(lambda app: {"Env": app.env, "Org": app.org, "Frontend version": app.frontend_version})
            .select({"Count": lambda group: group.length})
            .order_by(lambda group: (group.groupings["Org"], group.groupings["Frontend version"]))
        )

        # Backend frontend pairs in v4/v8
        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version.major == 8 and app.frontend_version.major == 4)
            .group_by(lambda app: {"Backend version": app.backend_version, "Frontend version": app.frontend_version})
            .order_by(lambda group: (group.length), reverse=True)
            .select({"Count": lambda group: group.length})
        )

        # Backend v8 version usage
        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version == "8.0.0")
            .group_by(lambda app: {"Env": app.env, "Org": app.org, "Backend version": app.backend_version})
            .order_by(lambda group: (group.length), reverse=True)
            .select({"Count": lambda group: group.length})
        )


        print()
        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
