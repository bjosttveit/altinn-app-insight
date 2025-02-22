from __future__ import annotations

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import cached_property, reduce
from io import BufferedReader
from itertools import compress, groupby, islice, starmap, tee
from pathlib import Path
from typing import Callable, Iterable, Iterator, TypeVar, cast
from zipfile import ZipFile

from tabulate import tabulate

from package import Environment, IterController, Version, VersionLock


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
    def __init__(self, apps: IterController[App]):
        self.__apps = apps

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = ["Env", "Org", "App", *self.list[0].data_keys]
        data = [[app.env, app.org, app.app, *app.data_values] for app in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.__apps.executor.shutdown()

    @property
    def list(self) -> list[App]:
        return self.__apps.list

    @property
    def length(self):
        return self.__apps.length

    @overload
    def __getitem__(self, key: int) -> App: ...
    @overload
    def __getitem__(self, key: slice) -> Apps: ...
    def __getitem__(self, key: int | slice):
        if isinstance(key, slice):
            return Apps(self.__apps[key])
        return self.__apps[key]

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

        return cls(IterController(apps, executor))

    def where(self, __func: Callable[[App], bool]) -> Apps:
        func = App.wrap_open_app(__func)
        return Apps(self.__apps.filter(func))

    def select(self, __func: Callable[[App], dict[str, object]]) -> Apps:
        func = App.wrap_with_data(App.wrap_open_app(__func))
        return Apps(self.__apps.map(func))

    def order_by(self, __func: Callable[[App], SupportsRichComparison], reverse=False) -> Apps:
        func = App.wrap_open_app(__func)
        return Apps(self.__apps.sort(func, reverse))

    def group_by(self, __group_func: Callable[[App], dict[str, SupportsRichComparison]]) -> GroupedApps:
        group_func = App.wrap_open_app(__group_func)
        return GroupedApps(
            self.__apps.group_by(lambda app: tuple(group_func(app).items()), lambda columns, apps: Group(dict(columns), apps))
        )


class Group:
    type Aggregators = dict[str, Callable[[Group], object]]

    def __init__(self, groupings: dict[str, object], apps: IterController[App], aggregators: Group.Aggregators = {}):
        self.groupings = groupings
        self.__apps = apps
        self.aggregators = aggregators

    def __repr__(self):
        headers = [*self.group_keys, *self.data_keys]
        data = [[*self.group_values, *self.data_values]]
        return tabulate(data, headers=headers, tablefmt="simple_grid")

    def with_aggregators(self, data: Group.Aggregators) -> Group:
        return Group(self.groupings, self.__apps, data)

    @staticmethod
    def wrap_with_aggregators(aggregators: Group.Aggregators) -> Callable[[Group], Group]:
        def func(group: Group):
            return group.with_aggregators(aggregators)

        return func

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

    @property
    def list(self) -> list[App]:
        return self.__apps.list

    @property
    def length(self):
        return self.__apps.length

    @property
    def is_empty(self):
        return self.__apps.is_empty

    @overload
    def __getitem__(self, key: int) -> App: ...
    @overload
    def __getitem__(self, key: slice) -> Apps: ...
    def __getitem__(self, key: int | slice):
        if isinstance(key, slice):
            return Apps(self.__apps[key])
        return self.__apps[key]

    def __len__(self):
        return self.length

    def where(self, __func: Callable[[App], bool]) -> Group:
        func = App.wrap_open_app(__func)
        return Group(self.groupings, self.__apps.filter(func), self.aggregators)

    T = TypeVar("T")

    def map_reduce[T](self, __map_func: Callable[[App], T], reduce_func: Callable[[T, T], T]) -> T | None:
        map_func = App.wrap_open_app(__map_func)
        return self.__apps.map(map_func).reduce(reduce_func)


class GroupedApps:
    def __init__(self, groups: IterController[Group]):
        self.__groups = groups

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = [*self.list[0].group_keys, *self.list[0].data_keys]
        data = [[*group.group_values, *group.data_values] for group in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.__groups.executor.shutdown()

    @property
    def list(self) -> list[Group]:
        return self.__groups.list

    @property
    def length(self):
        return self.__groups.length

    @overload
    def __getitem__(self, key: int) -> Group: ...
    @overload
    def __getitem__(self, key: slice) -> GroupedApps: ...
    def __getitem__(self, key: int | slice):
        if isinstance(key, slice):
            return GroupedApps(self.__groups[key])
        return self.__groups[key]

    def __len__(self):
        return self.length

    def apps_where(self, func: Callable[[App], bool]) -> GroupedApps:
        return GroupedApps(self.__groups.map(lambda group: group.where(func)).filter(lambda group: not group.is_empty))

    def group_where(self, func: Callable[[Group], bool]) -> GroupedApps:
        return GroupedApps(self.__groups.filter(func))

    def order_by(self, func: Callable[[Group], SupportsRichComparison], reverse=False) -> GroupedApps:
        return GroupedApps(self.__groups.sort(func, reverse))

    def group_select(self, aggregators: Group.Aggregators) -> GroupedApps:
        func = Group.wrap_with_aggregators(aggregators)
        return GroupedApps(self.__groups.map(func))


async def main():
    cache_dir = Path("./data")

    with Apps.init(cache_dir, max_open_files=100) as apps:

        start = time.time()

        # print(
        #     apps.where(
        #         lambda app: app.env == "prod"
        #         and app.frontend_version >= "4.0.0"
        #         and app.frontend_version != "4"
        #         and app.frontend_version.preview is None
        #     )
        #     .select(lambda app: {"Version": app.frontend_version})
        #     .order_by(lambda app: app.frontend_version)
        # )

        # apps_v4 = apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version.preview is None)
        # apps_locked = apps_v4.where(lambda app: app.frontend_version != "4")
        # print(f"{apps_locked.length} / {apps_v4.length}")

        # Apps testing navigation feature

        # Apps on different major versions frontend
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.exists)
        #     .group_by(lambda app: {"Frontend major version": cast(int, app.frontend_version.major)})
        #     .group_select({"Count": lambda group: group.length})
        #     .order_by(lambda group: (group.groupings["Frontend major version"],))
        # )

        # Apps on different major versions backend
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version.exists)
        #     .group_by(lambda app: {"Backend major version": cast(int, app.backend_version.major)})
        #     .group_select({"Count": lambda group: group.length})
        #     .order_by(lambda group: (group.groupings["Backend major version"],))
        # )

        # Apps in prod not running latest in v4
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
        #     .select(lambda app: {**app.data, "Frontend version": app.frontend_version})
        #     .order_by(lambda app: (app.org, app.frontend_version, app.app))
        # )

        # Service owners with locked app frontend per version
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
            .group_by(lambda app: {"Env": app.env, "Org": app.org, "Frontend version": app.frontend_version})
            .group_select(
                {
                    "Count": lambda group: group.length,
                    "Name": lambda group: group.map_reduce(lambda app: app.app, lambda a, b: min(a, b)),
                }
            )
            .order_by(lambda group: (group.groupings["Org"], group.groupings["Frontend version"]))
        )

        # Backend frontend pairs in v4/v8
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version.major == 8 and app.frontend_version.major == 4)
        #     .group_by(lambda app: {"Backend version": app.backend_version, "Frontend version": app.frontend_version})
        #     .order_by(lambda group: (group.length), reverse=True)
        #     .group_select({"Count": lambda group: group.length})
        # )

        # Backend v8 version usage
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version == "8.0.0")
        #     .group_by(lambda app: {"Env": app.env, "Org": app.org, "Backend version": app.backend_version})
        #     .order_by(lambda group: (group.length), reverse=True)
        #     .group_select({"Count": lambda group: group.length})
        # )

        print()
        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
