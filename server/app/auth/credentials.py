import json
import os
from pathlib import Path

CREDENTIAL_FIELDS = ("jira_base_url", "jira_email", "jira_api_token")
GITLAB_FIELDS = ("gitlab_url", "gitlab_token")
GITHUB_FIELDS = ("github_url", "github_token")
AI_FIELDS = ("anthropic_api_key", "gemini_api_key")


def read_saved_credentials(
    path: Path, fields: tuple[str, ...] = CREDENTIAL_FIELDS
) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if k in fields and v}


def save_credentials(
    path: Path, values: dict[str, str], fields: tuple[str, ...] = CREDENTIAL_FIELDS
) -> None:
    """Merge values into the saved credentials; omitted fields keep their value."""
    merged = {**read_saved_credentials(path, fields), **values}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(merged, f)
    os.replace(tmp, path)


def remove_credentials(path: Path, fields: tuple[str, ...]) -> None:
    """Forget the given saved fields; the others keep their value."""
    kept = {
        k: v
        for k, v in read_saved_credentials(path, AI_FIELDS).items()
        if k not in fields
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(kept, f)
    os.replace(tmp, path)
