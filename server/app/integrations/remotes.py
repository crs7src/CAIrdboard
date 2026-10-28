import asyncio
import re
from urllib.parse import urlsplit

from pydantic import BaseModel

PROJECT_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$")
REPO_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCP_REMOTE_RE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")


class HostError(Exception):
    """The git host was reachable but the request failed, or it could not be reached."""


class HostProject(BaseModel):
    provider: str
    path: str
    web_url: str
    default_branch: str | None


class ChangeRequest(BaseModel):
    """A GitLab merge request or a GitHub pull request."""

    iid: int
    web_url: str


def parse_remote(url: str) -> tuple[str, str] | None:
    """Split a git remote URL into (host, project path), or None if unrecognised."""
    url = url.strip()
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname, parts.path
    else:
        m = SCP_REMOTE_RE.match(url)
        if not m:
            return None
        host, path = m["host"], m["path"]
    path = path.strip("/").removesuffix(".git")
    if not host or not PROJECT_PATH_RE.match(path):
        return None
    return host.lower(), path


async def origin_remote(repo: str) -> tuple[str, str] | None:
    """(host, path) of the repo's origin remote, if it has a recognisable one."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo,
        "remote",
        "get-url",
        "origin",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    return parse_remote(out.decode())
