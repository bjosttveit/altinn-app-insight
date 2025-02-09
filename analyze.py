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
from itertools import compress, groupby, islice, tee
from pathlib import Path
from typing import Callable, Iterable, Iterator, TypeVar, cast
from zipfile import ZipFile

from tabulate import tabulate

from package import Environment, Version, VersionLock


class App:
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path, data={}):
        self.env: Environment = env
        self.org = org
        self.app = app
        self.__app_dir = app_dir
        self.data = data

    def __repr__(self):
        headers = ["Env", "Org", "App", *self.data.keys()]
        data = [[self.env, self.org, self.app, *self.data.values()]]
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


class Grouping(TypedDict):
    keys: dict[str, object]
    values: dict[str, object]
    apps: list[App]


G = TypeVar("G")


class Apps(Generic[G]):
    def __init__(self, apps: Iterable[App], executor: ThreadPoolExecutor, grouping: list[Grouping] | None = None):
        self.__apps = apps
        self.__executor = executor
        self.__grouping = grouping

    def __repr__(self):

        if self.__grouping is not None:
            if len(self.__grouping) == 0:
                print("Count: 0")

            headers = [*self.__grouping[0]["keys"].keys(), *self.__grouping[0]["values"].keys()]
            data = [[*group["keys"].values(), *group["values"].values()] for group in self.__grouping]
            table = tabulate(data, headers=headers, tablefmt="simple_grid")

            return f"{table}\nCount: {len(self.__grouping)}"

        if self.length == 0:
            print("Count: 0")

        headers = ["Env", "Org", "App", *self.list[0].data.keys()]
        data = [[app.env, app.org, app.app, *app.data.values()] for app in self.list]
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
    def init(cls, cache_dir: Path, max_open_files=100) -> Apps[App]:
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

        return cast(Apps[App], cls(apps, executor))

    T = TypeVar("T")

    # Uses a context manager to make sure any file operations are closed
    # Does not open any files yet, this happens lazily only when needed
    @staticmethod
    def wrap_open_app(__func: Callable[[App], T]) -> Callable[[App], T]:
        def func(app: App):
            with app as open_app:
                return __func(open_app)

        return func

    @staticmethod
    def wrap_open_app_list(__func: Callable[[list[App]], T]) -> Callable[[list[App]], T]:
        def func(__apps: list[App]):
            with ExitStack() as stack:
                apps = [stack.enter_context(app) for app in __apps]
                return __func(apps)

        return func

    # Creates a copy of the App instance with the data returned in the callback
    @staticmethod
    def wrap_with_data(__func: Callable[[App], dict[str, object]]) -> Callable[[App], App]:
        def func(app: App):
            return app.with_data(__func(app))

        return func

    def where(self, __func: Callable[[App], bool]) -> Apps[G]:
        a, b = self.__get_iter(2)
        func = Apps.wrap_open_app(__func)
        return Apps(compress(a, self.__executor.map(func, b)), self.__executor)

    def select(self, __func: Callable[[App], dict[str, object]]) -> Apps[G]:
        (a,) = self.__get_iter()
        func = Apps.wrap_with_data(Apps.wrap_open_app(__func))
        return Apps(self.__executor.map(func, a), self.__executor)

    def order_by(self, __func: Callable[[G], SupportsRichComparison], reverse=False) -> Apps[G]:
        (a,) = self.__get_iter()
        # Order apps
        if self.__grouping is None:
            func = Apps.wrap_open_app(__func)  # type: ignore
            return Apps(sorted(a, key=func, reverse=reverse), self.__executor)

        # Order groupings
        def group_func(group: Grouping):
            data = {**group["keys"], **group["values"]}
            return __func(data)  # type: ignore

        new_grouping = sorted(self.__grouping, key=group_func, reverse=reverse)

        return Apps(a, self.__executor, new_grouping)

    def group_by(self, group_func: Callable[[App], dict[str, SupportsRichComparison]]) -> Apps[dict[str, SupportsRichComparison]]:
        (a,) = self.__get_iter(1)

        def key_func(app: App) -> tuple[tuple[str, object], ...]:
            group = Apps.wrap_open_app(group_func)(app)
            return tuple(zip(group.keys(), group.values()))

        s = sorted(a, key=key_func)
        g = groupby(s, key=key_func)
        grouping: list[Grouping] = [{"keys": dict(keys), "values": {}, "apps": list(group)} for keys, group in g]
        return Apps(s, self.__executor, grouping)

    def aggregate(self, __agg_func: Callable[[list[App]], dict[str, object]]) -> Apps[G]:
        if self.__grouping is None:
            raise Exception("Apps.group_by must be used before Apps.aggregate")

        agg_func = Apps.wrap_open_app_list(__agg_func)

        new_grouping: list[Grouping] = []
        for group in self.__grouping:
            new_grouping.append({"keys": group["keys"], "values": agg_func(group["apps"]), "apps": group["apps"]})

        (a,) = self.__get_iter(1)
        return Apps(a, self.__executor, new_grouping)


async def main():
    cache_dir = Path("./data")

    with Apps.init(cache_dir, max_open_files=3) as apps:

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

        # print(
        #     apps.where(lambda app: app.frontend_version.preview is not None and "navigation" in app.frontend_version.preview).select(
        #         lambda app: {"Version": app.frontend_version}
        #     )
        # )

        # Apps in prod not running latest in v4
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
        #     .select(lambda app: {**app.data, "Frontend version": app.frontend_version})
        #     .order_by(lambda app: (app.org, app.frontend_version, app.app))
        # )

        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version == "4" and app.backend_version == "8.0.0").select(
        #         lambda app: {"Frontend version": app.frontend_version, "Backend version": app.backend_version}
        #     )
        # )

        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.backend_version.major == 8)
        #     .select(lambda app: {"Version pair": (app.backend_version, app.frontend_version)})
        #     .order_by(lambda app: (app.backend_version, app.frontend_version))
        # )

        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version.major == 8 and app.frontend_version.major == 4)
        #     .group_by(lambda app: {"Backend version": app.backend_version, "Frontend version": app.frontend_version})
        #     .aggregate(lambda apps: {"Count": len(apps)})
        #     .order_by(lambda data: data["Count"], reverse=True)
        # )

        print(
            apps.where(lambda app: app.env == "prod" and app.backend_version == "8.0.0")
            .group_by(lambda app: {"Env": app.env, "Org": app.org, "Backend version": app.backend_version})
            .aggregate(lambda apps: {"Count": len(apps)})
            .order_by(lambda data: data["Count"], reverse=True)
        )

        print()
        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
