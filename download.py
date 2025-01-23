import asyncio
import json
import os
import pickle
from asyncio import Queue
from asyncio.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

import aiofiles
import aiofiles.os
import httpx

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


class Keys(TypedDict):
    studioProd: str | None
    studioDev: str | None


@dataclass
class Context:
    cache_dir: Path
    prev_version_lock: VersionLock
    next_version_lock: VersionLock
    tokenProd: str | None
    tokenDev: str | None


@dataclass
class Cluster:
    env: Environment
    org: str

    @property
    def key(self):
        return f"{self.env}-{self.org}"


@dataclass
class Deployment:
    env: Environment
    org: str
    app: str
    version: str

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"


@dataclass
class Release:
    env: Environment
    org: str
    app: str
    version: str
    commit_sha: str
    dev: bool

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def repo_url(self):
        return (
            f"https://altinn.studio/repos/{self.org}/{self.app}.git"
            if not self.dev
            else f"https://dev.altinn.studio/repos/{self.org}/{self.app}.git"
        )

    @property
    def repo_download_url(self):
        return (
            f"https://altinn.studio/repos/{self.org}/{self.app}/archive/{self.commit_sha}.zip"
            if not self.dev
            else f"https://dev.altinn.studio/repos/{self.org}/{self.app}/archive/{self.commit_sha}.zip"
        )


def makeLock(release: Release, status: Status) -> LockData:
    return {
        "env": release.env,
        "org": release.org,
        "app": release.app,
        "version": release.version,
        "commit_sha": release.commit_sha,
        "status": status,
    }


def get_valid_envs(raw_envs: list[str]) -> list[Environment]:
    out: list[Environment] = []
    for raw in raw_envs:
        match raw:
            case "tt02":
                out.append("tt02")
            case "production":
                out.append("prod")
    return out


class RawOrg(TypedDict):
    environments: list[str]


class OrgsResponse(TypedDict):
    orgs: dict[str, RawOrg]


class RawDeployment(TypedDict):
    version: str
    release: str


class RawRelease(TypedDict):
    tagName: str
    targetCommitish: str


class ReleasesResponse(TypedDict):
    results: list[RawRelease]


class QueryClient:
    def __init__(self, context: Context, max_concurrent_requests=10, max_concurrent_downloads=10):
        self.context = context
        self.client = httpx.AsyncClient()

        self.request_queue = Queue()
        [self.request_queue.put_nowait(None) for _ in range(max_concurrent_requests)]

        self.download_queue = Queue()
        [self.download_queue.put_nowait(None) for _ in range(max_concurrent_downloads)]

        self.request_cache: dict[str, Future] = {}
        self.cache_path = Path.joinpath(self.context.cache_dir, ".request.cache")

        # TODO make cache serializable
        # if self.cache_path.exists():
        #     with open(self.cache_path, "rb") as f:
        #         self.request_cache = pickle.load(f)

    async def close(self):
        await self.client.aclose()
        # TODO make cache serializable
        # with open(self.cache_path, "wb") as f:
        #     pickle.dump(self.request_cache, f, protocol=pickle.HIGHEST_PROTOCOL)

    async def __get_remote_json(self, url: str, future: Future):
        await self.request_queue.get()
        try:
            res = await self.client.get(url)
            future.set_result(res.json())
        except Exception as e:
            future.set_exception(e)
        finally:
            self.request_queue.put_nowait(None)

    # Allows multiple requests for the same URL to only be called once and cached
    def __get_json(self, url: str) -> Future:
        cached_result = self.request_cache.get(url)
        if cached_result is not None:
            return cached_result
        future = asyncio.get_event_loop().create_future()
        self.request_cache[url] = future
        asyncio.create_task(self.__get_remote_json(url, future))
        return future

    async def fetch_clusters(self) -> list[Cluster] | None:
        res: OrgsResponse
        try:
            res = await self.__get_json("https://altinncdn.no/orgs/altinn-orgs.json")
        except:
            print("Failed to fetch clusters")
            return
        print("Fetched clusters")

        out: list[Cluster] = []
        for org, org_data in res["orgs"].items():
            envs = get_valid_envs(org_data["environments"])
            for env in envs:
                out.append(Cluster(env, org))
        return out

    async def fetch_deployments(self, cluster: Cluster) -> list[Deployment] | None:
        deployments_url = (
            f"https://{cluster.org}.apps.altinn.no/kuberneteswrapper/api/v1/deployments"
            if cluster.env == "prod"
            else f"https://{cluster.org}.apps.{cluster.env}.altinn.no/kuberneteswrapper/api/v1/deployments"
        )

        res: list[RawDeployment]
        try:
            res = await self.__get_json(deployments_url)
        except:
            print(f"Failed to fetch deployments for {cluster.key}")
            return
        print(f"Fetched deployments for {cluster.key}")

        out: list[Deployment] = []
        for deployment in res:
            release, version = deployment.get("release"), deployment.get("version")
            if release == "kuberneteswrapper":
                continue

            if release is None or version is None:
                continue

            app = release[len(f"{cluster.org}-") :]
            out.append(Deployment(cluster.env, cluster.org, app, version))

        return out

    async def try_fetch_release(self, deployment: Deployment, dev: bool) -> Release | None:
        try:
            res: ReleasesResponse = await self.__get_json(
                f"https://altinn.studio/designer/api/{deployment.org}/{deployment.app}/releases"
                if not dev
                else f"https://dev.altinn.studio/designer/api/{deployment.org}/{deployment.app}/releases"
            )
            for release in res["results"]:
                if release["tagName"] == deployment.version:
                    commit_sha = release["targetCommitish"]
                    return Release(
                        deployment.env, deployment.org, deployment.app, deployment.version, commit_sha, dev=False
                    )
        except:
            pass

    async def fetch_release(self, deployment: Deployment) -> Release | None:
        if self.context.tokenProd is not None:
            release_from_prod = await self.try_fetch_release(deployment, False)
            if release_from_prod is not None:
                print(f"Fetched releases for {deployment.key}")
                return release_from_prod

        # Check dev.altinn.studio if release was not found
        if self.context.tokenDev is not None:
            release_from_dev = await self.try_fetch_release(deployment, True)
            if release_from_dev is not None:
                print(f"Fetched releases for {deployment.key} (dev.altinn.studio)")
                return release_from_dev

        print(f"Could not find any matching releases for {deployment.key}")

    async def update_repository(self, release: Release):

        if (release.dev and self.context.tokenDev is None) or (not release.dev and self.context.tokenProd is None):
            print(f"Skipping {release.key} due to missing studio token")

        prev_version = self.context.prev_version_lock.get(release.key)

        if prev_version is not None and prev_version.get("status") == "failed":
            print(f"Skipping {release.key} due to previous failure")
            self.context.next_version_lock[release.key] = makeLock(release, "failed")
            return

        if prev_version is None or release.version != prev_version.get("version"):
            await self.download_queue.get()
            print(f"Downloading {release.key}")

            file_path = Path.joinpath(self.context.cache_dir, f"{release.key}.zip")
            try:
                async with aiofiles.open(file_path, "wb") as f:
                    async with self.client.stream(
                        "GET",
                        release.repo_download_url,
                        follow_redirects=True,
                        headers={
                            "Authorization": f"token {self.context.tokenProd if not release.dev else self.context.tokenDev}"
                        },
                    ) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=4096):
                            await f.write(chunk)

                self.context.next_version_lock[release.key] = makeLock(release, "success")
            except Exception:
                print(f"Failed to download {release.key}")
                self.context.next_version_lock[release.key] = makeLock(release, "failed")
                try:
                    await aiofiles.os.remove(file_path)
                except:
                    pass
            finally:
                self.download_queue.put_nowait(None)
        else:
            print(f"Already up to date: {release.key}")
            self.context.next_version_lock[release.key] = makeLock(release, "success")


async def main():

    key_path = Path("./key.json")
    keys: Keys
    if key_path.exists():
        with open(key_path, "r") as f:
            keys = json.load(f)
            if keys.get("studioProd") is None and keys.get("studioDev") is None:
                print("Please provide studio access tokens 'studioProd' and 'studioDev' in a 'keys.json' file")
                exit(1)
    else:
        print("Please provide studio access tokens 'studioProd' and 'studioDev' in a 'keys.json' file")
        exit(1)

    cache_dir = Path("./data")
    os.makedirs(cache_dir, exist_ok=True)

    lock_path = Path.joinpath(cache_dir, ".apps.lock.json")

    prev_version_lock: VersionLock = {}
    if lock_path.exists():
        with open(lock_path, "r") as f:
            prev_version_lock = json.load(f)

    next_version_lock: VersionLock = {}

    client = QueryClient(
        Context(cache_dir, prev_version_lock, next_version_lock, keys.get("studioProd"), keys.get("studioDev")),
        max_concurrent_requests=20,
        max_concurrent_downloads=20,
    )

    async def stage_1(cluster: Cluster):
        deployments = await client.fetch_deployments(cluster)
        if deployments is not None:
            await asyncio.gather(*[stage_2(deployment) for deployment in deployments])

    async def stage_2(deployment: Deployment):
        release = await client.fetch_release(deployment)
        if release is not None:
            await client.update_repository(release)

    clusters = await client.fetch_clusters()

    if clusters is not None:
        try:
            await asyncio.gather(*[stage_1(cluster) for cluster in clusters])

            # Remove apps that no longer exist
            for key in prev_version_lock.keys():
                if next_version_lock.get(key) is None:
                    print(f"Removing {key}")
                    Path.joinpath(cache_dir, f"{key}.zip").unlink(missing_ok=True)
        except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
            pass

        # Update lock file
        with open(lock_path, "w") as f:
            json.dump(next_version_lock, f, indent=2)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
