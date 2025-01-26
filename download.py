import argparse
import asyncio
import json
import os
from asyncio import Queue
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlparse

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
    dev_altinn_studio: bool


class Keys(TypedDict):
    studioProd: str | None
    studioDev: str | None


class Args:
    retry_failed: bool


@dataclass
class Context:
    args: Args
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
        "dev_altinn_studio": release.dev,
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
    def __init__(self, context: Context, max_concurrent_requests=2):
        self.context = context
        self.client = httpx.AsyncClient()
        self.max_concurrent_requests = max_concurrent_requests
        self.queues: dict[str, Queue] = {}

    async def close(self):
        await self.client.aclose()

    async def queue_get(self, url: str):
        domain = urlparse(url).netloc
        if (queue := self.queues.get(domain)) is None:
            queue = Queue()
            [queue.put_nowait(None) for _ in range(self.max_concurrent_requests)]
            self.queues[domain] = queue

        await queue.get()

    def queue_put(self, url: str):
        domain = urlparse(url).netloc
        self.queues[domain].put_nowait(None)

    async def __fetch_json(self, url: str):
        await self.queue_get(url)
        try:
            res = await self.client.get(url)
            return res.json()
        finally:
            self.queue_put(url)

    async def fetch_clusters(self) -> list[Cluster] | None:
        res: OrgsResponse
        try:
            res = await self.__fetch_json("https://altinncdn.no/orgs/altinn-orgs.json")
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
            res = await self.__fetch_json(deployments_url)
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
            res: ReleasesResponse = await self.__fetch_json(
                f"https://altinn.studio/designer/api/{deployment.org}/{deployment.app}/releases"
                if not dev
                else f"https://dev.altinn.studio/designer/api/{deployment.org}/{deployment.app}/releases"
            )
            for release in res["results"]:
                if release["tagName"] == deployment.version:
                    commit_sha = release["targetCommitish"]
                    return Release(
                        deployment.env,
                        deployment.org,
                        deployment.app,
                        deployment.version,
                        commit_sha,
                        dev,
                    )
        except:
            pass

    async def fetch_release(self, deployment: Deployment) -> Release | None:
        prev_version = self.context.prev_version_lock.get(deployment.key)

        if prev_version is not None:
            if prev_version.get("status") == "failed" and not self.context.args.retry_failed:
                print(f"Skipping {deployment.key} due to previous failure")
                self.context.next_version_lock[deployment.key] = prev_version
                return

            if (
                prev_version.get("status") == "failed"
                and self.context.args.retry_failed
                and deployment.version == prev_version.get("version")
            ):
                print(f"Using cached release for {deployment.key}")
                return Release(
                    deployment.env,
                    deployment.org,
                    deployment.app,
                    deployment.version,
                    prev_version.get("commit_sha"),
                    prev_version.get("dev_altinn_studio"),
                )

            if prev_version.get("status") == "success" and deployment.version == prev_version.get("version"):
                print(f"Already up to date: {deployment.key}")
                self.context.next_version_lock[deployment.key] = prev_version
                return

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
        prev_version = self.context.prev_version_lock.get(release.key)

        if (release.dev and self.context.tokenDev is None) or (not release.dev and self.context.tokenProd is None):
            print(f"Skipping {release.key} due to missing studio token")
            if prev_version is not None:
                self.context.next_version_lock[release.key] = prev_version
            return

        await self.queue_get(release.repo_download_url)
        file_path = Path.joinpath(self.context.cache_dir, f"{release.key}.zip")
        try:
            async with aiofiles.open(file_path, "wb") as f:
                async with self.client.stream(
                    "GET",
                    release.repo_download_url,
                    follow_redirects=True,
                    headers={"Authorization": f"token {self.context.tokenProd if not release.dev else self.context.tokenDev}"},
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        await f.write(chunk)

            print(f"Successfully downloaded {release.key}")
            self.context.next_version_lock[release.key] = makeLock(release, "success")
        except Exception:
            print(f"Failed to download {release.key}")
            self.context.next_version_lock[release.key] = makeLock(release, "failed")
            try:
                await aiofiles.os.remove(file_path)
            except:
                pass
        finally:
            self.queue_put(release.repo_download_url)


async def main(args: Args):

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
        Context(args, cache_dir, prev_version_lock, next_version_lock, keys.get("studioProd"), keys.get("studioDev")),
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
    parser = argparse.ArgumentParser(description="Download Altinn apps")
    parser.add_argument(
        "--retry-failed",
        help="Retry downloading apps that previously failed",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    args = parser.parse_args(namespace=Args())
    asyncio.run(main(args))
