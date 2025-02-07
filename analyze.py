from __future__ import annotations

import asyncio
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import total_ordering
from io import BufferedReader
from itertools import compress, tee
from pathlib import Path
from typing import (Callable, Iterable, Iterator, Literal, Self, TypedDict,
                    TypeVar)

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

VERSION_REGEX = r"^(\d+)(.(\d+))?(.(\d+))?(-(.+))?$"

class Version(str):
    def __init__(self, version_string: str | None):
        self.__version_string = version_string
        self.__match = re.match(VERSION_REGEX, version_string) if version_string is not None else None
        self.major = int(self.__match.group(1)) if self.__match and self.__match.group(1) is not None else None
        self.minor = int(self.__match.group(3)) if self.__match and self.__match.group(3) is not None else None
        self.patch = int(self.__match.group(5)) if self.__match and self.__match.group(5) is not None else None
        self.preview = self.__match.group(7) if self.__match and self.__match.group(7) is not None else None

    def __repr__(self):
        return self.__version_string if self.__version_string is not None else "None"

    def __le__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self == other or self < other

    def __ge__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self == other or self > other

    def __ne__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self.__version_string != other.__version_string

    def __eq__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self.__version_string == other.__version_string

    def __lt__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        if self.major is None or other.major is None:
            # This should never happen since it will not match unless this exists
            return NotImplemented
        if self.major != other.major:
            return self.major < other.major

        if self.minor != other.minor:
            if self.minor is None:
                return False
            if other.minor is None:
                return True
            return self.minor < other.minor

        if self.patch != other.patch:
            if self.patch is None:
                return False
            if other.patch is None:
                return True
            return self.patch < other.patch

        if self.preview != other.preview:
            if self.preview is None:
                return True
            if other.preview is None:
                return False


        return False

    def __gt__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        if self.major is None or other.major is None:
            # This should never happen since it will not match unless this exists
            return NotImplemented
        if self.major != other.major:
            return self.major > other.major

        if self.minor != other.minor:
            if self.minor is None:
                return True
            if other.minor is None:
                return False
            return self.minor > other.minor

        if self.patch != other.patch:
            if self.patch is None:
                return True
            if other.patch is None:
                return False
            return self.patch > other.patch

        if self.preview != other.preview:
            if self.preview is None:
                return False
            if other.preview is None:
                return True


        return False

    @property
    def exists(self):
        return self.__match is not None

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
    __frontend_version: Version | None = None
    __backend_version: Version | None = None

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
        if self.__frontend_version is not None:
            return self.__frontend_version
        match = self.first_match(
            r"/App/views/Home/Index.cshtml$",
            r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"',
        )
        self.__frontend_version = Version(match.group(1)) if match is not None else Version(None)
        return self.__frontend_version

    @property
    def backend_version(self) -> Version:
        if self.__backend_version is not None:
            return self.__backend_version
        match = self.first_match(
            r"/App/[^/]+.csproj$",
            r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"',
        )
        self.__backend_version = Version(match.group(3)) if match is not None else Version(None)
        return self.__backend_version


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

    def where_content(self, __func: Callable[[AppContent], bool]) -> Apps:
        a, b = self.__get_iter(2)
        func = wrap_func_app_open(__func)
        return Apps(compress(a, self.__executor.map(func, b)), self.__executor)

    def select_meta(self, func: Callable[[AppMeta], T]) -> Iterable[T]:
        (a,) = self.__get_iter()
        return map(func, a)

    def select_content(self, __func: Callable[[AppContent], T]) -> Iterable[T]:
        (a,) = self.__get_iter()
        func = wrap_func_app_open(__func)
        return self.__executor.map(func, a)


async def main():
    cache_dir = Path("./data")

    with Apps.init(cache_dir, max_open_files=2) as apps:

        start = time.time()


        data = apps.where_meta(lambda app: app.env == 'prod').where_content(lambda app: app.frontend_version > "3.0.0" and app.frontend_version < "4.0.0")
        print(data.length())
        # data = (
        #     apps.where_meta(lambda app: app.env == "prod")
        #     .where_content(lambda app: app.frontend_version == "4" and app.backend_version == "8.0.0")
        #     .select_content(lambda app: (app.frontend_version, app.backend_version))
        # )
        # print(list(data))

        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
