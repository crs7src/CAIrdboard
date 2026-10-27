import json
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_credentials_file: Path = Path("data/jira.json")
    ai_config_file: Path = Path("data/ai_config.json")
    plans_dir: Path = Path("data/plans")
    skills_dir: Path = Path("data/skills")
    copilot_command: str = "copilot"
    plan_timeout_seconds: float = 900
    implementations_dir: Path = Path("data/implementations")
    implement_timeout_seconds: float = 3600
    feedback_dir: Path = Path("data/feedback")
    feedback_timeout_seconds: float = 1800
    test_runs_dir: Path = Path("data/test_runs")
    test_timeout_seconds: float = 1200
    test_ready_timeout_seconds: float = 90
    reviews_dir: Path = Path("data/reviews")
    review_timeout_seconds: float = 1800

    @property
    def jira_configured(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)


CREDENTIAL_FIELDS = ("jira_base_url", "jira_email", "jira_api_token")


def read_saved_credentials(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if k in CREDENTIAL_FIELDS and v}


def save_credentials(path: Path, values: dict[str, str]) -> None:
    """Merge values into the saved credentials; omitted fields keep their value."""
    merged = {**read_saved_credentials(path), **values}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(merged, f)
    os.replace(tmp, path)


def get_settings() -> Settings:
    """Saved credentials override .env; re-read per request so changes apply immediately."""
    settings = Settings()
    saved = read_saved_credentials(settings.jira_credentials_file)
    return settings.model_copy(update=saved)
