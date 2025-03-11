from dataclasses import dataclass
from typing import Literal, TypedDict

FETCH_FAILED = "fetch-failed"

type Environment = Literal["prod", "tt02"]
type VersionLock = dict[str, LockData]
type Status = Literal["success", "failed"]


class LockData(TypedDict):
    env: Environment
    org: str
    app: str
    version: str
    commit_sha: str
    status: Status
    dev_altinn_studio: bool


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
