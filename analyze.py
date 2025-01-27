import asyncio
import json
import os
import pickle
import re
import zipfile
from asyncio import Queue
from asyncio.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, TypedDict

import aiofiles
import aiofiles.os

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


@dataclass
class App:
    env: Environment
    org: str
    app: str
    app_dir: Path

    read_queue: Queue

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.app_dir.joinpath(self.file_name)

    def first_match(self, file_pattern: str, line_pattern: str) -> re.Match[str] | None:
        with open(self.file_path, "rb") as f:
            with zipfile.ZipFile(f) as z:
                file_names = filter(lambda name: re.search(file_pattern, name) is not None, z.namelist())
                for name in file_names:
                    with z.open(name) as zf:
                        for line in zf.readlines():
                            match = re.search(line_pattern, line.decode())
                            if match is not None:
                                return match

    @property
    def frontend_version(self):
        match = self.first_match(
            r"/App/views/Home/Index.cshtml$",
            r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"',
        )
        if match is not None:
            return match.group(1)

    @property
    def backend_version(self):
        match = self.first_match(
            r"/App/[^/]+.csproj$",
            r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"',
        )
        if match is not None:
            return match.group(3)


class Apps:
    def __init__(self, cache_dir: Path, max_open_files=100):
        lock_path = Path.joinpath(cache_dir, ".apps.lock.json")
        if not lock_path.exists():
            print("Failed to locate lock file")
            exit(1)

        self.read_queue = Queue()
        [self.read_queue.put_nowait(None) for _ in range(max_open_files)]

        with open(lock_path, "r") as f:
            lock_file: VersionLock = json.load(f)

        self.apps: list[App] = []
        for lock_data in lock_file.values():
            if lock_data["status"] == "success":
                self.apps.append(App(lock_data["env"], lock_data["org"], lock_data["app"], cache_dir, self.read_queue))

    def where(self, func: Callable[[App], bool]) -> list[App]:
        return list(filter(func, self.apps))


async def main():
    cache_dir = Path("./data")

    apps = Apps(cache_dir)

    # print(len(apps))
    # for app in apps:
    #     print(f"{app.key}: {get_app_backend_version(app)} | {get_apps_frontend_version(app)}")

    print(len(apps.where(lambda app: app.env == "prod" and app.frontend_version == "4")))


if __name__ == "__main__":
    asyncio.run(main())
