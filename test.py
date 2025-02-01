import asyncio
import json
import time
from concurrent.futures import (ALL_COMPLETED, ThreadPoolExecutor,
                                as_completed, wait)
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

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

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.app_dir.joinpath(self.file_name)

def read_file(app: App):
    with open(app.file_path, 'rb') as f:
        return f.read()


async def main():
    cache_dir = Path("./data")
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

    start = time.time()

    # for app in apps:
    #     read_file(app)

    executor = ThreadPoolExecutor(max_workers=100)
    futures = [executor.submit(read_file, app) for app in apps]
    for future in as_completed(futures):
        future.result()

    executor.shutdown()

    print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
