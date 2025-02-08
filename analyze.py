from __future__ import annotations

import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import cached_property
from io import BufferedReader
from itertools import compress, islice, tee
from pathlib import Path
from typing import Callable, Iterable, Iterator, Self, TypeVar, cast
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


class Apps:
    def __init__(self, apps: Iterable[App], executor: ThreadPoolExecutor):
        self.__apps = apps
        self.__executor = executor

    def __repr__(self):
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
    def init(cls, cache_dir: Path, max_open_files=100) -> Self:
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

    def where(self, __func: Callable[[App], bool]) -> Apps:
        a, b = self.__get_iter(2)
        func = Apps.wrap_open_app(__func)
        return Apps(compress(a, self.__executor.map(func, b)), self.__executor)

    def select(self, __func: Callable[[App], dict[str, object]]) -> Apps:
        (a,) = self.__get_iter()
        func = Apps.wrap_with_data(Apps.wrap_open_app(__func))
        return Apps(self.__executor.map(func, a), self.__executor)


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

        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4").select(
        #         lambda app: {**app.data, "Version": app.frontend_version}
        #     )
        # )

        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version == "4" and app.backend_version == "8.0.0").select(
        #         lambda app: {"Frontend version": app.frontend_version, "Backend version": app.backend_version}
        #     )
        # )

        print(
            apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.backend_version.major == 8).select(
                lambda app: {"Frontend version": app.frontend_version, "Backend version": app.backend_version}
            )[:10]
        )

        print()
        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
