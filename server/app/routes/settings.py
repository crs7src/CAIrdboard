from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import skills
from app.core.ai_config import AiConfig, load_ai_config, save_ai_config
from app.deps import (
    SettingsDep,
)

router = APIRouter()


@router.get("/api/ai-config")
def get_ai_config(settings: SettingsDep) -> AiConfig:
    return load_ai_config(settings.ai_config_file)


@router.put("/api/ai-config")
def put_ai_config(config: AiConfig, settings: SettingsDep) -> AiConfig:
    # Older clients (the AI settings tab) send no names; keep the saved ones.
    if "project_names" not in config.model_fields_set:
        config.project_names = load_ai_config(settings.ai_config_file).project_names
    if "auto_review" not in config.model_fields_set:
        config.auto_review = load_ai_config(settings.ai_config_file).auto_review
    config.project_names = {
        k: n for k, n in config.project_names.items() if k in config.project_repos
    }
    save_ai_config(settings.ai_config_file, config)
    return config


class SkillInfo(BaseModel):
    step: str
    content: str
    default_content: str
    customized: bool


class SkillUpdate(BaseModel):
    content: str


def skill_info(step: str) -> SkillInfo:
    try:
        default = skills.read_default(step)
        override = skills.read_override(step)
    except skills.SkillError as e:
        raise HTTPException(500, str(e)) from e
    return SkillInfo(
        step=step,
        content=default if override is None else override,
        default_content=default,
        customized=override is not None,
    )


def check_step(step: str) -> None:
    if step not in skills.STEPS:
        raise HTTPException(404, f"Unknown step '{step}'")


@router.get("/api/skills")
def list_skills() -> list[SkillInfo]:
    return [skill_info(step) for step in skills.STEPS]


@router.put("/api/skills/{step}")
def put_skill(step: str, body: SkillUpdate) -> SkillInfo:
    check_step(step)
    try:
        skills.save_override(step, body.content)
    except skills.SkillError as e:
        raise HTTPException(422, str(e)) from e
    return skill_info(step)


@router.delete("/api/skills/{step}")
def reset_skill(step: str) -> SkillInfo:
    """Remove the user's override so the bundled default is used again."""
    check_step(step)
    skills.delete_override(step)
    return skill_info(step)


class DirEntry(BaseModel):
    name: str
    is_git: bool


class DirListing(BaseModel):
    path: str
    parent: str | None
    dirs: list[DirEntry]


@router.get("/api/fs/dirs")
def list_dirs(path: str | None = None) -> DirListing:
    """List sub-folders (never files) of a directory, for the repo picker."""
    target = Path(path).expanduser() if path else Path.home()
    if not target.is_absolute() or not target.is_dir():
        raise HTTPException(404, "Folder not found")
    target = target.resolve()
    dirs: list[DirEntry] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            dirs.append(DirEntry(name=child.name, is_git=(child / ".git").exists()))
    except PermissionError:
        raise HTTPException(403, "Permission denied") from None
    parent = str(target.parent) if target.parent != target else None
    return DirListing(path=str(target), parent=parent, dirs=dirs)
