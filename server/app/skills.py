import os
import re
from pathlib import Path

from app.config import Settings

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "skills"
BUNDLED_NAMES = {
    "planner": "card-planner",
    "implementer": "card-implementer",
    "reviewer": "card-reviewer",
}
STEPS = tuple(BUNDLED_NAMES)
PLANNER_MODES = ("default", "reopened")

# Added to every prompt in code, so a customised skill cannot drop it.
AGENTS_PREAMBLE = (
    "Before doing anything else, check the repository in your current working directory "
    "for `AGENTS.md` and `.github/copilot-instructions.md`. If either exists, read it "
    "and follow its instructions throughout, except where they conflict with the "
    "restrictions in this prompt."
)


class SkillError(Exception):
    pass


def skills_dir() -> Path:
    return Settings().skills_dir


def default_path(step: str) -> Path:
    return BUNDLED_DIR / BUNDLED_NAMES[step] / "SKILL.md"


def override_path(step: str) -> Path:
    return skills_dir() / f"{step}.md"


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        text = text.split("---", 2)[-1]
    return text.strip()


def read_default(step: str) -> str:
    path = default_path(step)
    try:
        return path.read_text()
    except OSError as e:
        raise SkillError(f"The default {step} skill could not be read: {path}") from e


def read_override(step: str) -> str | None:
    try:
        return override_path(step).read_text()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise SkillError(f"The custom {step} skill could not be read") from e


def read(step: str) -> str:
    """The skill text for a step: the user's override if there is one, else the default."""
    override = read_override(step)
    return override if override is not None else read_default(step)


def validate(step: str, content: str) -> None:
    if not content.strip():
        raise SkillError("The skill cannot be empty")
    if step == "planner":
        modes = {
            m.strip().casefold()
            for m in re.findall(r"^## Mode: (.+)$", content, re.MULTILINE)
        }
        missing = [m for m in PLANNER_MODES if m not in modes]
        if missing:
            raise SkillError(
                "The planner skill needs these sections: "
                + ", ".join(f"'## Mode: {m}'" for m in missing)
            )


def save_override(step: str, content: str) -> None:
    validate(step, content)
    path = override_path(step)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def delete_override(step: str) -> None:
    override_path(step).unlink(missing_ok=True)
