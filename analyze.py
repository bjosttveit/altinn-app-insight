from __future__ import annotations

from typing import TYPE_CHECKING

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
from pathlib import Path
from typing import Callable, TypeVar, cast
from zipfile import ZipFile

from tabulate import tabulate

from package import Environment, IterContainer, IterController, Version, VersionLock


class App:
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path, data: dict[str, object] = {}):
        self.env: Environment = env
        self.org = org
        self.app = app
        self.__app_dir = app_dir
        self.data = data

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.__app_dir.joinpath(self.file_name)

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

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.data.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return list(self.data.values())

    T = TypeVar("T")

    # Uses a context manager to make sure any file operations are closed
    # Does not open any files yet, this happens lazily only when needed
    @staticmethod
    def wrap_open_app(__func: Callable[[App], T]) -> Callable[[App], T]:
        def func(app: App):
            with app as open_app:
                return __func(open_app)

        return func

    # Creates a copy of the App instance with the data returned in the callback
    @staticmethod
    def wrap_with_data(__func: Callable[[App], dict[str, object]]) -> Callable[[App], App]:
        def func(app: App):
            return app.with_data(__func(app))

        return func

    __file: BufferedReader | None = None
    __zip_file: ZipFile | None = None
    __files: list[str] | None = None

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


class Apps(IterController[App]):
    def __init__(self, apps: IterContainer[App], groupings: dict[str, object] = {}, selector: dict[str, Callable[[Apps], object]] = {}):
        super().__init__(apps)
        self.groupings = groupings
        self.selector = selector

    def with_iterable(self, iterable: IterContainer[App]):
        return Apps(iterable, self.groupings, self.selector)

    def with_selector(self, data: dict[str, Callable[[Apps], object]]) -> Apps:
        return Apps(self.i, self.groupings, data)

    @staticmethod
    def wrap_with_selector(selector: dict[str, Callable[[Apps], object]]) -> Callable[[Apps], Apps]:
        def func(apps: Apps):
            return apps.with_selector(selector)

        return func

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = ["Env", "Org", "App", *self.list[0].data_keys]
        data = [[app.env, app.org, app.app, *app.data_values] for app in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

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

        return cls(IterContainer(apps, executor))

    @cached_property
    def group_keys(self) -> list[str]:
        return list(self.groupings.keys())

    @cached_property
    def group_values(self) -> list[object]:
        return list(self.groupings.values())

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.selector.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return [func(self) for func in self.selector.values()]

    def where(self, __func: Callable[[App], bool]) -> Apps:
        func = App.wrap_open_app(__func)
        return self.with_iterable(self.i.filter(func))

    def select(self, selector: dict[str, Callable[[App], object]]) -> Apps:
        func = App.wrap_with_data(App.wrap_open_app(lambda app: {key: func(app) for (key, func) in selector.items()}))
        return self.with_iterable(self.i.map(func))

    def order_by(self, __func: Callable[[App], SupportsRichComparison], reverse=False) -> Apps:
        func = App.wrap_open_app(__func)
        return self.with_iterable(self.i.sort(func, reverse))

    def group_by(self, grouper: dict[str, Callable[[App], SupportsRichComparison]]) -> GroupedApps:
        key_func = App.wrap_open_app(lambda app: tuple([(key, func(app)) for (key, func) in grouper.items()]))
        map_func = lambda columns, apps: Apps(apps, dict(columns), self.selector)
        return GroupedApps(self.i.group_by(key_func, map_func))

    T = TypeVar("T")

    def map_reduce[T](self, __map_func: Callable[[App], T], reduce_func: Callable[[T, T], T]) -> T | None:
        map_func = App.wrap_open_app(__map_func)
        return self.i.map(map_func).reduce(reduce_func)


class GroupedApps(IterController[Apps]):
    def __init__(self, groups: IterContainer[Apps]):
        super().__init__(groups)

    def with_iterable(self, iterable):
        return GroupedApps(iterable)

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = [*self.list[0].group_keys, *self.list[0].data_keys]
        data = [[*group.group_values, *group.data_values] for group in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    def where(self, func: Callable[[Apps], bool]) -> GroupedApps:
        return self.with_iterable(self.i.filter(func))

    def order_by(self, func: Callable[[Apps], SupportsRichComparison], reverse=False) -> GroupedApps:
        return self.with_iterable(self.i.sort(func, reverse))

    def select(self, selector: dict[str, Callable[[Apps], object]]) -> GroupedApps:
        func = Apps.wrap_with_selector(selector)
        return self.with_iterable(self.i.map(func))


async def main():
    cache_dir = Path("./data")

    with Apps.init(cache_dir, max_open_files=100) as apps:

        start = time.time()

        print(
            apps.where(
                lambda app: app.env == "prod"
                and app.frontend_version >= "4.0.0"
                and app.frontend_version != "4"
                and app.frontend_version.preview is None
            )
            .select({"Version": lambda app: app.frontend_version})
            .order_by(lambda app: app.frontend_version)
        )

        # apps_v4 = apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version.preview is None)
        # apps_locked = apps_v4.where(lambda app: app.frontend_version != "4")
        # print(f"{apps_locked.length} / {apps_v4.length}")

        # Apps testing navigation feature

        # Apps on different major versions frontend
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.exists)
            .group_by({"Frontend major version": lambda app: cast(int, app.frontend_version.major)})
            .select({"Count": lambda apps: apps.length})
            .order_by(lambda apps: (apps.groupings["Frontend major version"],))
        )

        # Apps on different major versions backend
        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version.exists)
            .group_by({"Backend major version": lambda app: cast(int, app.backend_version.major)})
            .select({"Count": lambda apps: apps.length})
            .order_by(lambda apps: (apps.groupings["Backend major version"],))
        )

        # Apps in prod not running latest in v4
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
            .select({"Frontend version": lambda app: app.frontend_version})
            .order_by(lambda app: (app.org, app.frontend_version, app.app))
        )

        # Service owners with locked app frontend per version
        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
            .group_by({"Env": lambda app: app.env, "Org": lambda app: app.org, "Frontend version": lambda app: app.frontend_version})
            .select(
                {
                    "Count": lambda apps: apps.length,
                    "Name": lambda apps: apps.map_reduce(lambda app: app.app, lambda a, b: min(a, b)),
                }
            )
            .order_by(lambda apps: (apps.groupings["Org"], apps.groupings["Frontend version"]))
        )

        # Backend frontend pairs in v4/v8
        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version.major == 8 and app.frontend_version.major == 4)
            .group_by({"Backend version": lambda app: app.backend_version, "Frontend version": lambda app: app.frontend_version})
            .order_by(lambda apps: (apps.length), reverse=True)
            .select({"Count": lambda apps: apps.length})
        )

        # Backend v8 version usage
        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version == "8.0.0")
            .group_by({"Env": lambda app: app.env, "Org": lambda app: app.org, "Backend version": lambda app: app.backend_version})
            .order_by(lambda apps: (apps.length), reverse=True)
            .select({"Count": lambda apps: apps.length})
        )

        print()
        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
