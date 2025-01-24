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
from typing import Literal, TypedDict

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


@dataclass
class App:
    env: Environment
    org: str
    app: str
    app_dir: Path

    data: bytes | None = None

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.app_dir.joinpath(self.file_name)


def get_apps(
    lock_file: VersionLock, cache_dir: Path, env: Environment | None = None, org: str | None = None
) -> list[App]:
    apps: list[App] = []
    for lock_data in lock_file.values():
        if lock_data["status"] == "failed":
            continue
        if env is not None and lock_data["env"] != env:
            continue
        if org is not None and lock_data["org"] != org:
            continue
        apps.append(App(lock_data["env"], lock_data["org"], lock_data["app"], cache_dir))

    return apps


def first_match(app: App, file_pattern: str, line_pattern: str) -> re.Match[str] | None:
    with open(app.file_path, "rb") as f:
        with zipfile.ZipFile(f) as z:
            file_names = filter(lambda name: re.search(file_pattern, name) is not None, z.namelist())
            for name in file_names:
                with z.open(name) as zf:
                    for line in zf.readlines():
                        match = re.search(line_pattern, line.decode())
                        if match is not None:
                            return match


def get_apps_frontend_version(app: App):
    match = first_match(
        app,
        r"/App/views/Home/Index.cshtml$",
        r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"',
    )
    if match is not None:
        return match.group(1)


def get_app_backend_version(app: App):
    match = first_match(
        app,
        r"/App/[^/]+.csproj$",
        r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"',
    )
    if match is not None:
        return match.group(3)


async def main():
    cache_dir = Path("./data")
    lock_path = Path.joinpath(cache_dir, ".apps.lock.json")

    version_lock: VersionLock = {}
    if lock_path.exists():
        with open(lock_path, "r") as f:
            version_lock = json.load(f)

    apps = get_apps(version_lock, cache_dir, env="tt02", org="ttd")
    # print(len(apps))
    for app in apps:
        print(f"{app.key}: {get_app_backend_version(app)} | {get_apps_frontend_version(app)}")


if __name__ == "__main__":
    asyncio.run(main())
