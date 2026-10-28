import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

DEFAULT_ELIGIBLE_STATUSES = [
    "Backlog",
    "Ready to Play",
    "DEV In Progress",
    "Merge Requested",
    "To Do",
    "In Progress",
    "Reopened",
]


PROVIDER_IDS = ("copilot", "anthropic", "gemini")


def _known_provider(value: str) -> str:
    value = value.strip().lower()
    if value not in PROVIDER_IDS:
        raise ValueError(f"Unknown AI provider '{value}'")
    return value


class AiConfig(BaseModel):
    eligible_statuses: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ELIGIBLE_STATUSES)
    )
    # Jira project key (e.g. "ABC") -> absolute path of the repo to plan in.
    project_repos: dict[str, str] = Field(default_factory=dict)
    # Project key -> display name shown on the Projects page.
    project_names: dict[str, str] = Field(default_factory=dict)
    # Start the review automatically when an implementation completes.
    auto_review: bool = True
    # AI provider used when a project has none of its own.
    default_provider: str = "copilot"
    # Project key -> AI provider id, for projects that differ from the default.
    project_providers: dict[str, str] = Field(default_factory=dict)
    # Provider id -> model override (blank means the provider's default).
    provider_models: dict[str, str] = Field(default_factory=dict)

    @field_validator("eligible_statuses")
    @classmethod
    def clean_statuses(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s.strip()]
        if not cleaned:
            raise ValueError("At least one eligible status is required")
        return cleaned

    @field_validator("project_repos")
    @classmethod
    def clean_repos(cls, v: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, path in v.items():
            key, path = key.strip().upper(), path.strip()
            if not key or not path:
                raise ValueError("Project keys and repo paths must not be empty")
            if not Path(path).is_absolute():
                raise ValueError(f"Repo path for {key} must be absolute")
            cleaned[key] = path
        return cleaned

    @field_validator("project_names")
    @classmethod
    def clean_names(cls, v: dict[str, str]) -> dict[str, str]:
        return {
            key.strip().upper(): name.strip()
            for key, name in v.items()
            if key.strip() and name.strip()
        }

    @field_validator("default_provider")
    @classmethod
    def known_default(cls, v: str) -> str:
        return _known_provider(v)

    @field_validator("project_providers")
    @classmethod
    def clean_providers(cls, v: dict[str, str]) -> dict[str, str]:
        return {
            key.strip().upper(): _known_provider(provider)
            for key, provider in v.items()
            if key.strip()
        }

    @field_validator("provider_models")
    @classmethod
    def clean_models(cls, v: dict[str, str]) -> dict[str, str]:
        return {_known_provider(p): m.strip() for p, m in v.items() if m.strip()}

    def is_eligible(self, status: str, source: str = "jira") -> bool:
        # An open GitHub issue is always plannable; its only other state is Closed.
        if source == "github" and status == "Open":
            return True
        wanted = status.strip().casefold()
        return any(s.casefold() == wanted for s in self.eligible_statuses)

    def repo_for(self, project: str) -> str | None:
        return self.project_repos.get(project.upper())


def load_ai_config(path: Path) -> AiConfig:
    try:
        return AiConfig.model_validate(json.loads(path.read_text()))
    except FileNotFoundError, json.JSONDecodeError, ValueError:
        return AiConfig()


def save_ai_config(path: Path, config: AiConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(config.model_dump_json(indent=2))
    os.replace(tmp, path)
