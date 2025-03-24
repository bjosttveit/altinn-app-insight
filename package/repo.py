from dataclasses import dataclass
from typing import Literal, TypedDict

FETCH_FAILED = "fetch-failed"

type Environment = Literal["prod", "tt02"]
type StudioEnvironment = Literal["prod", "staging", "dev"]
type VersionLock = dict[str, LockData]
type Status = Literal["success", "failed"]

type Keys = dict[StudioEnvironment, str | None]


class LockData(TypedDict):
    env: Environment
    org: str
    app: str
    version: str
    commit_sha: str
    status: Status
    studio_env: StudioEnvironment


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
    studio_env: StudioEnvironment

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def repo_url(self):
        return (
            f"https://altinn.studio/repos/{self.org}/{self.app}.git"
            if self.studio_env == "prod"
            else f"https://{self.studio_env}.altinn.studio/repos/{self.org}/{self.app}.git"
        )

    @property
    def repo_download_url(self):
        return (
            f"https://altinn.studio/repos/{self.org}/{self.app}/archive/{self.commit_sha}.zip"
            if self.studio_env == "prod"
            else f"https://{self.studio_env}.altinn.studio/repos/{self.org}/{self.app}/archive/{self.commit_sha}.zip"
        )


def makeLock(release: Release, status: Status) -> LockData:
    return {
        "env": release.env,
        "org": release.org,
        "app": release.app,
        "version": release.version,
        "commit_sha": release.commit_sha,
        "status": status,
        "studio_env": release.studio_env,
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
