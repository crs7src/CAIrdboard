from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.auth.credentials import (
    AI_FIELDS,
    GITHUB_FIELDS,
    GITLAB_FIELDS,
    read_saved_credentials,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_credentials_file: Path = Path("data/jira.json")
    gitlab_url: str = ""
    gitlab_token: str = ""
    gitlab_credentials_file: Path = Path("data/gitlab.json")
    # The API URL; for GitHub Enterprise use https://HOST/api/v3.
    github_url: str = "https://api.github.com"
    github_token: str = ""
    github_credentials_file: Path = Path("data/github.json")
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    ai_credentials_file: Path = Path("data/ai_credentials.json")
    ai_config_file: Path = Path("data/ai_config.json")
    db_file: Path = Path("data/cairdboard.db")
    # Folders of JSON files written before the SQLite database; imported once at startup.
    plans_dir: Path = Path("data/plans")
    skills_dir: Path = Path("data/skills")
    copilot_command: str = "copilot"
    plan_timeout_seconds: float = 900
    implementations_dir: Path = Path("data/implementations")
    implement_timeout_seconds: float = 3600
    feedback_dir: Path = Path("data/feedback")
    feedback_timeout_seconds: float = 1800
    test_runs_dir: Path = Path("data/test_runs")
    test_configs_dir: Path = Path("data/test_configs")
    test_timeout_seconds: float = 1200
    test_ready_timeout_seconds: float = 90
    reviews_dir: Path = Path("data/reviews")
    review_timeout_seconds: float = 1800

    @property
    def jira_configured(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)

    @property
    def gitlab_configured(self) -> bool:
        return bool(self.gitlab_url and self.gitlab_token)

    @property
    def github_configured(self) -> bool:
        return bool(self.github_url and self.github_token)


def get_settings() -> Settings:
    """Saved credentials override .env; re-read per request so changes apply immediately."""
    settings = Settings()
    saved = read_saved_credentials(settings.jira_credentials_file)
    saved |= read_saved_credentials(settings.gitlab_credentials_file, GITLAB_FIELDS)
    saved |= read_saved_credentials(settings.github_credentials_file, GITHUB_FIELDS)
    saved |= read_saved_credentials(settings.ai_credentials_file, AI_FIELDS)
    return settings.model_copy(update=saved)
