import asyncio
from asyncio import Queue
from contextlib import asynccontextmanager, suppress
from functools import reduce
from itertools import groupby, starmap
import json
import os
from pathlib import Path
from typing import Any, Callable, TypedDict
from urllib.parse import urlparse

from rich.console import Console, Group
from rich.live import Live
from rich.columns import Columns

from package.repo import (
    Cluster,
    Deployment,
    Environment,
    Keys,
    LockData,
    Release,
    StudioEnvironment,
    VersionLock,
    get_valid_envs,
    makeLock,
)

from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.status import Status
import aiofiles
import aiofiles.os
import httpx


class RawOrg(TypedDict):
    environments: list[str]


class OrgsResponse(TypedDict):
    orgs: dict[str, RawOrg]


class RawDeployment(TypedDict):
    version: str
    release: str


type DeploymentsResponse = list[RawDeployment]


class RawRelease(TypedDict):
    tagName: str
    targetCommitish: str


class ReleasesResponse(TypedDict):
    results: list[RawRelease]


class BaseQueryClient:
    def __init__(self, max_concurrent_requests_per_domain=4, max_retries=3, debug=False):
        self.console = Console()
        self.debug = debug
        self.max_concurrent_requests_per_domain = max_concurrent_requests_per_domain
        self.max_retries = max_retries
        self.queues: dict[str, Queue[None]] = {}

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            http2=True, limits=httpx.Limits(max_connections=20, max_keepalive_connections=20, keepalive_expiry=None)
        )
        return self

    async def __aexit__(self, *args, **kwargs):
        await self.client.aclose()

    @asynccontextmanager
    async def request_queue(self, url: str):
        domain = urlparse(url).netloc

        if (queue := self.queues.get(domain)) is None:
            # Initialize queue if missing
            queue = Queue[None]()
            [queue.put_nowait(None) for _ in range(self.max_concurrent_requests_per_domain)]
            self.queues[domain] = queue

        await queue.get()
        try:
            yield
        finally:
            self.queues[domain].put_nowait(None)

    async def fetch_json(self, url: str, attempt=1) -> Any:
        async with self.request_queue(url):
            try:
                res = await self.client.get(url)
                return res.json()
            except httpx.ReadTimeout:
                # Common source of flaky errors
                if attempt >= self.max_retries:
                    raise
                if self.debug:
                    self.console.print(f"[yellow] fetch_json: retrying url '{url}', attempt {attempt + 1}")
                await asyncio.sleep(1.0)
                return await self.fetch_json(url, attempt + 1)

    async def download_file(
        self, url: str, file_path: Path, token: str, on_progress: Callable[[int, int], None] | None = None, attempt=1
    ):
        async with self.request_queue(url):
            try:
                async with aiofiles.open(file_path, "wb") as f:
                    async with self.client.stream(
                        "GET",
                        url,
                        follow_redirects=True,
                        headers={"Authorization": f"token {token}"},
                    ) as response:
                        response.raise_for_status()
                        total = int(response.headers["Content-Length"])
                        if on_progress:
                            on_progress(response.num_bytes_downloaded, total)

                        async for chunk in response.aiter_bytes(chunk_size=4096):
                            await f.write(chunk)
                            if on_progress:
                                on_progress(response.num_bytes_downloaded, total)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # This is common, and means it will always fail so no point in retrying
                    raise
                if attempt >= self.max_retries:
                    raise
                if self.debug:
                    self.console.print(f"[yellow] download_file: retrying url '{url}', attempt {attempt + 1}")
                return self.download_file(url, file_path, token, on_progress, attempt + 1)


class QueryClient(BaseQueryClient):
    def __init__(
        self,
        key_path: Path,
        cache_dir: Path,
        retry_failed: bool,
        max_concurrent_requests_per_domain=4,
        debug=False,
    ):
        super().__init__(max_concurrent_requests_per_domain, debug=debug)
        self.key_path = key_path
        self.cache_dir = cache_dir
        self.retry_failed = retry_failed

        os.makedirs(cache_dir, exist_ok=True)

        self.keys = self.read_studio_keys()
        self.prev_version_lock = self.read_version_lock()
        self.next_version_lock: VersionLock = {}

        # Progress
        self.deployments_progress = Progress(
            SpinnerColumn(finished_text="[green]✓[/]"),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("- [bold cyan]{task.fields[n_deployments]}[/] deployments"),
        )
        self.deployments_task = self.deployments_progress.add_task(
            "Fetching deployments", visible=False, total=None, n_deployments=0
        )

        self.apps_progress = Progress(
            SpinnerColumn(finished_text="[green]✓[/]"),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        )
        self.apps_task = self.apps_progress.add_task("Updating deployments", visible=False, total=None)

        self.download_progress = Progress(
            SpinnerColumn(finished_text="[green]✓[/]"),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        )
        self.progress_group = Group(self.deployments_progress, self.apps_progress, self.download_progress)

        # Statistics
        self.fetch_orgs_failed = False
        self.orgs_count = 0
        self.cluster_count = 0
        self.fetch_deployments_success: list[Cluster] = []
        self.fetch_deployments_failed: list[Cluster] = []
        self.fetch_deployments_with_existing_apps_failed: list[Cluster] = []
        self.deployment_count = 0
        self.fetch_releases_failed: list[tuple[Deployment, StudioEnvironment]] = []
        self.fetch_releases_success: list[tuple[Deployment, StudioEnvironment]] = []
        self.skipped_releases_failure: list[Deployment] = []
        self.already_up_to_date_releases: list[Deployment] = []
        self.fetch_release_with_existing_app_failed: list[Deployment] = []
        self.no_matching_releases: list[Deployment] = []
        self.releases_count = 0
        self.download_success: list[Release] = []
        self.download_failed: list[Release] = []
        self.apps_removed_count = 0
        self.total_apps_count = 0
        self.apps_count: dict[Environment, int] = {}

    def read_studio_keys(self) -> Keys:
        if not self.key_path.exists():
            raise Exception(
                "Missing studio access token file 'keys.json', please copy the provided 'keys.template.json' and add one or more tokens."
            )
        with open(self.key_path, "r") as f:
            keys: Keys | None = json.load(f)
        if keys is None or not (keys.get("prod") or keys.get("staging") or keys.get("dev")):
            raise Exception(
                "Please provide at least one studio access token of 'prod', 'staging', or 'dev' in the 'keys.json' file."
            )
        return keys

    @property
    def lock_path(self):
        return self.cache_dir.joinpath(".apps.lock.json")

    def read_version_lock(self) -> VersionLock:
        if not self.lock_path.exists():
            return {}
        with open(self.lock_path, "r") as f:
            return json.load(f)

    def write_version_lock(self, version_lock: VersionLock):
        with open(self.lock_path, "w") as f:
            json.dump(version_lock, f, indent=2)

        # Count the total number of successful apps for each environment
        is_success: Callable[[LockData], bool] = lambda lock_data: lock_data["status"] == "success"
        get_env: Callable[[LockData], Environment] = lambda lock_data: lock_data["env"]
        self.apps_count = dict(
            starmap(
                lambda env, apps: (env, len(list(apps))),
                groupby(sorted(filter(is_success, version_lock.values()), key=get_env), key=get_env),
            )
        )
        self.total_apps_count = reduce(lambda t, i: t + i, self.apps_count.values(), 0)

    def remove_undeployed_apps(self):
        for key in self.prev_version_lock.keys():
            if self.next_version_lock.get(key) is None:
                self.cache_dir.joinpath(f"{key}.zip").unlink(missing_ok=True)
                self.apps_removed_count += 1

    async def fetch_orgs(self) -> OrgsResponse | None:
        try:
            return await self.fetch_json("https://altinncdn.no/orgs/altinn-orgs.json")
        except:
            self.fetch_orgs_failed = True
            return None

    async def get_clusters(self) -> list[Cluster]:
        orgs_response = await self.fetch_orgs()
        orgs = orgs_response["orgs"] if orgs_response is not None else {}
        clusters = [
            Cluster(env, org) for (org, org_data) in orgs.items() for env in get_valid_envs(org_data["environments"])
        ]
        self.orgs_count += len(list(filter(lambda org: len(org["environments"]) > 0, orgs.values())))
        self.cluster_count += len(clusters)
        return clusters

    async def fetch_deployments(self, cluster: Cluster) -> DeploymentsResponse | None:
        try:
            res = await self.fetch_json(
                f"https://{cluster.org}.apps.altinn.no/kuberneteswrapper/api/v1/deployments"
                if cluster.env == "prod"
                else f"https://{cluster.org}.apps.{cluster.env}.altinn.no/kuberneteswrapper/api/v1/deployments"
            )
            self.fetch_deployments_success.append(cluster)
            return res
        except:
            # If fetching deployments fails for some reason, but we already have matching apps
            # Copy them over in the lock file so they are not deleted, and warn that they could not be updated
            # TODO: Possibly add a flag to disable this, in case the cluster has been deleted
            failed_with_existing_apps = False
            for key, lock_data in self.prev_version_lock.items():
                if lock_data["env"] == cluster.env and lock_data["org"] == cluster.org:
                    failed_with_existing_apps = True
                    self.next_version_lock[key] = self.prev_version_lock[key]

            if failed_with_existing_apps:
                if self.debug:
                    self.console.print_exception()
                self.fetch_deployments_with_existing_apps_failed.append(cluster)

            self.fetch_deployments_failed.append(cluster)
            return None

    async def get_deployments(self, cluster: Cluster) -> list[Deployment]:
        deployments_response = await self.fetch_deployments(cluster)
        deployments = (
            [
                Deployment(
                    env=cluster.env,
                    org=cluster.org,
                    app=deployment["release"].removeprefix(f"{cluster.org}-"),
                    version=deployment["version"],
                )
                for deployment in deployments_response
                if deployment.get("release") is not None
                and deployment["release"] != "kuberneteswrapper"
                and deployment.get("version") is not None
            ]
            if deployments_response is not None
            else []
        )
        self.deployment_count += len(deployments)
        return deployments

    async def fetch_release(self, deployment: Deployment, studio_env: StudioEnvironment) -> ReleasesResponse | None:
        try:
            res = await self.fetch_json(
                f"https://altinn.studio/designer/api/{deployment.org}/{deployment.app}/releases"
                if studio_env == "prod"
                else f"https://{studio_env}.altinn.studio/designer/api/{deployment.org}/{deployment.app}/releases"
            )
            self.fetch_releases_success.append((deployment, studio_env))
            return res
        except:
            # If a release is in a different studio environment, this will usually not fail, just return an empty list
            self.fetch_releases_failed.append((deployment, studio_env))
            return None

    async def get_release(self, deployment: Deployment) -> Release | None:
        prev_version = self.prev_version_lock.get(deployment.key)
        prev_studio_env = prev_version["studio_env"] if prev_version is not None else None

        if prev_version is not None:
            if prev_version.get("status") == "failed" and not self.retry_failed:
                # Skip due to previous failure
                self.skipped_releases_failure.append(deployment)
                self.next_version_lock[deployment.key] = prev_version
                return None

            if (
                prev_version.get("status") == "failed"
                and self.retry_failed
                and deployment.version == prev_version.get("version")
            ):
                # Retry failed repo, release data from lock file is up to date so just return that
                self.releases_count += 1
                return Release(
                    env=deployment.env,
                    org=deployment.org,
                    app=deployment.app,
                    version=deployment.version,
                    commit_sha=prev_version.get("commit_sha"),
                    studio_env=prev_version.get("studio_env"),
                )

            if prev_version.get("status") == "success" and deployment.version == prev_version.get("version"):
                # Already up to date, copy lock information and return None (no need to download repo)
                self.already_up_to_date_releases.append(deployment)
                self.next_version_lock[deployment.key] = prev_version
                return None

        # Try fetching release from each studio environment (unless we already know which env it is), return the first match
        envs_to_check: list[StudioEnvironment] = (
            [prev_studio_env] if prev_studio_env is not None else list(self.keys.keys())
        )
        for studio_env in envs_to_check:
            key = self.keys.get(studio_env)
            if not key:
                # Skip due to missing token
                if prev_version is not None:
                    self.next_version_lock[deployment.key] = prev_version
                continue
            releases_response = await self.fetch_release(deployment, studio_env)
            if releases_response is None:
                if prev_studio_env is not None and self.debug:
                    self.console.print_exception()
                continue
            for releases_response in releases_response["results"]:
                if releases_response["tagName"] == deployment.version:
                    self.releases_count += 1
                    return Release(
                        env=deployment.env,
                        org=deployment.org,
                        app=deployment.app,
                        version=deployment.version,
                        commit_sha=releases_response["targetCommitish"],
                        studio_env=studio_env,
                    )

        # No matching releases for deployment

        # If fetching release fails for some reason, but we already have the app
        # Copy it over in the lock file so it is not deleted, and warn that it could not be updated
        # TODO: Possibly add a flag to disable this, in case this is permanent
        if prev_version is not None:
            self.next_version_lock[deployment.key] = prev_version
            self.fetch_release_with_existing_app_failed.append(deployment)

        # TODO: This seems to happen sometimes, why is it flaky?
        self.no_matching_releases.append(deployment)
        return None

    async def update_apps(self):
        with Status("Fetching clusters", console=self.console):
            clusters = await self.get_clusters()
        self.console.print(f"[green]✓[/] Fetching clusters - {self.orgs_count} orgs, {self.cluster_count} clusters")

        with Live(self.progress_group, refresh_per_second=10, console=self.console):
            if clusters is not None:
                self.deployments_progress.update(self.deployments_task, total=len(clusters), visible=True)
                await asyncio.gather(*[self.update_cluster(cluster) for cluster in clusters])
                # The display has some trouble updating completely in Jupyter
                self.deployments_progress.refresh()
                self.apps_progress.refresh()
                self.download_progress.refresh()
                await asyncio.sleep(0.1)

        self.remove_undeployed_apps()
        self.write_version_lock(self.next_version_lock)

        if len(self.fetch_deployments_with_existing_apps_failed) > 0:
            clusters = ", ".join(
                map(lambda cluster: f"{cluster.env}/{cluster.org}", self.fetch_deployments_with_existing_apps_failed)
            )
            self.console.print(
                f":warning-emoji: [yellow] Fetching deployments for {clusters} failed and could not be updated. [/]"
            )

        if len(self.fetch_release_with_existing_app_failed) > 0:
            deployments = ", ".join(
                map(
                    lambda deployment: f"{deployment.env}/{deployment.org}/{deployment.app}",
                    self.fetch_release_with_existing_app_failed,
                )
            )
            self.console.print(
                f":warning-emoji: [yellow] Fetching release for {deployments} failed and could not be updated. [/]"
            )

        basic_stats = [f"{len(self.download_success)} updated", f"{len(self.download_failed)} failed"]
        if len(self.already_up_to_date_releases) > 0:
            basic_stats.append(f"{len(self.already_up_to_date_releases)} already up to date")
        if len(self.skipped_releases_failure) > 0:
            basic_stats.append(f"{len(self.skipped_releases_failure)} skipped due to previous failure")
        if len(self.no_matching_releases) > 0:
            basic_stats.append(f"{len(self.no_matching_releases)} skipped due to no matching releases")
        if self.apps_removed_count > 0:
            basic_stats.append(f"{self.apps_removed_count} apps removed")
        self.console.print(Columns(basic_stats))

        app_stats = starmap(lambda env, count: f"{count} apps in {env}", self.apps_count.items())
        self.console.print(Columns(app_stats))

    async def update_cluster(self, cluster: Cluster):
        deployments = await self.get_deployments(cluster)
        self.deployments_progress.update(self.deployments_task, advance=1, n_deployments=self.deployment_count)
        self.apps_progress.update(self.apps_task, total=self.deployment_count, visible=True)

        await asyncio.gather(*[self.update_deployment(deployment) for deployment in deployments])

    async def update_deployment(self, deployment: Deployment):
        release = await self.get_release(deployment)
        if release is not None:
            await self.update_repository(release)

        self.apps_progress.advance(self.apps_task)

    async def update_repository(self, release: Release):
        prev_version = self.prev_version_lock.get(release.key)

        if not (token := self.keys[release.studio_env]):
            # Skipping due to missing token, should not ever happen here, but in get_release
            if prev_version is not None:
                self.next_version_lock[release.key] = prev_version
            return None

        task_id = self.download_progress.add_task(f"[green]{release.env}[/]: {release.org}/{release.app}", total=None)
        file_path = self.cache_dir.joinpath(f"{release.key}.zip")
        try:
            await self.download_file(
                release.repo_download_url,
                file_path,
                token,
                lambda completed, total: self.download_progress.update(task_id, completed=completed, total=total),
            )
            self.download_success.append(release)
            self.next_version_lock[release.key] = makeLock(release, "success")
        except:
            self.download_failed.append(release)
            self.next_version_lock[release.key] = makeLock(release, "failed")
            with suppress(FileNotFoundError):
                await aiofiles.os.remove(file_path)

        self.download_progress.remove_task(task_id)
