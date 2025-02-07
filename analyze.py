from __future__ import annotations

import asyncio
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import total_ordering
from io import BufferedReader
from itertools import compress, tee
from pathlib import Path
from typing import Callable, Iterable, Iterator, Literal, Self, TypedDict, TypeVar

FETCH_FAILED = "fetch-failed"

type Environment = Literal["prod", "tt02"]
type VersionLock = dict[str, LockData]
type Status = Literal["success"] | Literal["failed"]


class LockData(TypedDict):
    env: Environment
    org: str
    app: str
    version: str
    commit_sha: str
    status: Status
    dev_altinn_studio: bool


@total_ordering
class Version:
    def __init__(self, version_string: str | None):
        self.version_string = version_string

    def __repr__(self):
        return self.version_string if self.version_string is not None else "None"

    def __eq__(self, other):
        other_version_string = other.version_string if isinstance(other, Version) else other if type(other) == str else None

        if other_version_string is None:
            return NotImplemented

        return other_version_string == self.version_string

    def __lt__(self, other):
        other_version_string = other.version_string if isinstance(other, Version) else other if type(other) == str else None

        if other_version_string is None:
            return NotImplemented

        # TODO: Implement less than operator
        return True

    @property
    def exists(self):
        return self.version_string is not None


class AppMeta:
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path):
        self.env: Environment = env
        self.org = org
        self.app = app
        self.__app_dir = app_dir

    def __repr__(self):
        return self.key

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.__app_dir.joinpath(self.file_name)

    def open(self) -> AppContent:
        f = open(self.file_path, "rb")
        return AppContent(self.env, self.org, self.app, self.__app_dir, f)


class AppContent(AppMeta):
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path, file: BufferedReader):
        super().__init__(env, org, app, app_dir)
        self.__file = file
        self.__zip_file = zipfile.ZipFile(self.__file)
        self.files = self.__zip_file.namelist()

    def open(self) -> AppContent:
        raise Exception("App is already open")

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.__zip_file.close()
        self.__file.close()

    def first_match(self, file_pattern: str, line_pattern: str) -> re.Match[str] | None:
        file_names = filter(lambda name: re.search(file_pattern, name) is not None, self.files)
        for name in file_names:
            with self.__zip_file.open(name) as zf:
                for line in zf.readlines():
                    match = re.search(line_pattern, line.decode())
                    if match is not None:
                        return match

    @property
    def frontend_version(self) -> Version:
        match = self.first_match(
            r"/App/views/Home/Index.cshtml$",
            r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"',
        )
        if match is not None:
            return Version(match.group(1))
        return Version(None)

    @property
    def backend_version(self) -> Version:
        match = self.first_match(
            r"/App/[^/]+.csproj$",
            r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"',
        )
        if match is not None:
            return Version(match.group(3))
        return Version(None)


T = TypeVar("T")


def wrap_func_app_open(func: Callable[[AppContent], T]) -> Callable[[AppMeta], T]:
    def __func(app: AppMeta):
        with app.open() as app_data:
            return func(app_data)

    return __func


class Apps:
    def __init__(self, apps: Iterable[AppMeta], executor: ThreadPoolExecutor):
        self.__apps = apps
        self.__apps_list: list[AppMeta] | None = None
        self.__executor = executor

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.__executor.shutdown()

    def __get_iter(self, n: int = 1) -> tuple[Iterator[AppMeta], ...]:
        tup = tee(self.__apps, n + 1)
        self.__apps = tup[0]
        return tup[1:]

    def __get_list(self) -> list[AppMeta]:
        if self.__apps_list is None:
            (iterator,) = self.__get_iter()
            self.__apps_list = list(iterator)

        return self.__apps_list

    def length(self):
        return len(self.__get_list())

    def to_list(self):
        return self.__get_list()

    @classmethod
    def init(cls, cache_dir: Path, max_open_files=100) -> Self:
        lock_path = Path.joinpath(cache_dir, ".apps.lock.json")
        if not lock_path.exists():
            print("Failed to locate lock file")
            exit(1)

        with open(lock_path, "r") as f:
            lock_file: VersionLock = json.load(f)

        apps: list[AppMeta] = []
        for lock_data in lock_file.values():
            if lock_data["status"] == "success":
                apps.append(AppMeta(lock_data["env"], lock_data["org"], lock_data["app"], cache_dir))

        executor = ThreadPoolExecutor(max_workers=max_open_files)

        return cls(apps, executor)

    def where_meta(self, func: Callable[[AppMeta], bool]) -> Apps:
        (a,) = self.__get_iter()
        return Apps(filter(func, a), self.__executor)

    def where(self, __func: Callable[[AppContent], bool]) -> Apps:
        a, b = self.__get_iter(2)
        func = wrap_func_app_open(__func)
        return Apps(compress(a, self.__executor.map(func, b)), self.__executor)

    def select_meta(self, func: Callable[[AppMeta], T]) -> Iterable[T]:
        (a,) = self.__get_iter()
        return map(func, a)

    def select(self, __func: Callable[[AppContent], T]) -> Iterable[T]:
        (a,) = self.__get_iter()
        func = wrap_func_app_open(__func)
        return self.__executor.map(func, a)


async def main():
    cache_dir = Path("./data")

    with Apps.init(cache_dir, max_open_files=2) as apps:

        start = time.time()

        data = (
            apps.where_meta(lambda app: app.env == "prod")
            .where(lambda app: app.frontend_version == "4" and app.backend_version == "8.0.0")
            .select(lambda app: (app.frontend_version, app.backend_version))
        )
        print(list(data))

        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
