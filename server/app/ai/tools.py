"""Repo tools for providers that have no built-in ones.

By default only the read-only `view`, `grep` and `glob` exist. The agent toolset adds
`edit`, `create` and a restricted `bash`. Everything is confined to the repo: paths are
resolved (symlinks included) and must stay inside it, nothing under `.git` can be
written, and `bash` runs in the repo with a deny-list (no push, branch, rebase,
reset --hard, clean, rm -rf, sudo), a timeout and an output cap.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path

MAX_OUTPUT_CHARS = 30_000
MAX_FILE_BYTES = 1_000_000
MAX_RESULTS = 200
MAX_ITERATIONS = 20
MAX_AGENT_ITERATIONS = 100
BASH_TIMEOUT = 120
SKIPPED_DIRS = {".git", "node_modules", ".venv", "__pycache__"}

TOOL_SPECS = [
    {
        "name": "view",
        "description": (
            "Read a text file (with line numbers) or list a directory. "
            "Paths are relative to the repo root."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or folder path"},
                "start_line": {"type": "integer", "description": "First line, 1-based"},
                "end_line": {"type": "integer", "description": "Last line, inclusive"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search file contents with a regular expression. Returns path:line:text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression"},
                "path": {"type": "string", "description": "Folder or file to search"},
                "glob": {
                    "type": "string",
                    "description": "Only files matching this glob",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "glob",
        "description": "Find files by glob pattern, such as src/**/*.py.",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
]

AGENT_TOOL_SPECS = [
    {
        "name": "edit",
        "description": (
            "Replace one exact occurrence of old_str with new_str in a file. "
            "old_str must match exactly once."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "create",
        "description": "Create a new file (parent folders are made). Fails if it exists.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Run a shell command in the repo root (for tests, builds and git add/commit). "
            "git push, branch, rebase, reset --hard, clean, rm -rf and sudo are refused."
        ),
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]


def tool_specs(agent: bool = False) -> list[dict]:
    return TOOL_SPECS + AGENT_TOOL_SPECS if agent else TOOL_SPECS


class ToolError(Exception):
    pass


def _cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n[output truncated]"


# Commands that run other commands could hide a denied one from the check.
_WRAPPERS = {"sudo", "eval", "exec", "xargs", "nohup", "su", "doas"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def denied_reason(command: str) -> str | None:
    """Why a shell command is refused, or None when it may run."""
    if "`" in command or "$(" in command or "<(" in command or ">(" in command:
        return "command substitution is not allowed"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as e:
        return f"cannot parse the command ({e})"
    segment: list[str] = []
    for token in [*tokens, ";"]:
        if token and set(token) <= set(";&|\n"):
            reason = _segment_reason(segment)
            if reason:
                return reason
            segment = []
        else:
            segment.append(token)
    return None


def _segment_reason(words: list[str]) -> str | None:
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]
    if not words:
        return None
    name = Path(words[0]).name
    args = words[1:]
    if name in _WRAPPERS:
        return f"'{name}' is not allowed"
    if name in _SHELLS and any(a.startswith("-") and "c" in a[1:] for a in args):
        return "nested shells are not allowed"
    if name == "rm":
        flags = {a for a in args if a.startswith("-")}
        short = "".join(a[1:] for a in flags if not a.startswith("--"))
        recursive = "r" in short.lower() or "--recursive" in flags
        force = "f" in short or "--force" in flags
        if recursive and force:
            return "rm -rf is not allowed"
    if name == "git":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in _GIT_OPTS_WITH_VALUE else 1
        sub = args[i] if i < len(args) else ""
        rest = args[i + 1 :]
        if sub in {"push", "branch", "rebase", "clean"}:
            return f"git {sub} is not allowed"
        if sub == "reset" and "--hard" in rest:
            return "git reset --hard is not allowed"
    return None


class ToolBox:
    def __init__(self, repo: str, agent: bool = False):
        self.root = Path(repo).resolve()
        self.agent = agent

    def call(self, name: str, args: object) -> str:
        """Run a tool; failures come back as text so the model can adjust."""
        args = args if isinstance(args, dict) else {}
        try:
            if name == "view":
                return _cap(self._view(args))
            if name == "grep":
                return _cap(self._grep(args))
            if name == "glob":
                return _cap(self._glob(args))
            if self.agent and name == "edit":
                return self._edit(args)
            if self.agent and name == "create":
                return self._create(args)
            if self.agent and name == "bash":
                return _cap(self._bash(args))
            raise ToolError(f"Unknown tool '{name}'")
        except ToolError as e:
            return f"Error: {e}"
        except (OSError, re.error, ValueError, TypeError) as e:
            return f"Error: {e}"

    def _resolve(self, value: object) -> Path:
        text = str(value or ".")
        path = (self.root / text).resolve()
        if not path.is_relative_to(self.root):
            raise ToolError("Path is outside the repo")
        if not path.exists():
            raise ToolError(f"Path not found: {text}")
        return path

    def _writable(self, value: object) -> Path:
        text = str(value or "")
        if not text:
            raise ToolError("A path is required")
        path = (self.root / text).resolve()
        if not path.is_relative_to(self.root):
            raise ToolError("Path is outside the repo")
        if ".git" in path.relative_to(self.root).parts:
            raise ToolError("Files under .git cannot be changed")
        return path

    def _edit(self, args: dict) -> str:
        path = self._writable(args.get("path"))
        if not path.is_file():
            raise ToolError(f"File not found: {args.get('path')}")
        old, new = args.get("old_str"), args.get("new_str")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ToolError("old_str and new_str are required")
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            raise ToolError("File is not text") from None
        if text.count(old) != 1:
            raise ToolError(
                f"old_str must match exactly once (found {text.count(old)})"
            )
        path.write_text(text.replace(old, new))
        return f"Edited {self._rel(path)}"

    def _create(self, args: dict) -> str:
        path = self._writable(args.get("path"))
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content is required")
        if path.exists():
            raise ToolError("File already exists; use edit")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"Created {self._rel(path)}"

    def _bash(self, args: dict) -> str:
        command = str(args.get("command") or "").strip()
        if not command:
            raise ToolError("A command is required")
        reason = denied_reason(command)
        if reason:
            raise ToolError(f"Refused: {reason}")
        try:
            done = subprocess.run(
                ["/bin/sh", "-c", command],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=BASH_TIMEOUT,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"Command timed out after {BASH_TIMEOUT}s") from None
        out = (done.stdout or "") + (done.stderr or "")
        return f"exit code {done.returncode}\n{out}"

    def _inside(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return resolved.is_relative_to(self.root) and not (
            SKIPPED_DIRS & set(path.relative_to(self.root).parts)
        )

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _view(self, args: dict) -> str:
        path = self._resolve(args.get("path"))
        if path.is_dir():
            entries = sorted(
                (c for c in path.iterdir() if self._inside(c)),
                key=lambda c: (not c.is_dir(), c.name.lower()),
            )
            return "\n".join(
                self._rel(c) + ("/" if c.is_dir() else "")
                for c in entries[:MAX_RESULTS]
            )
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("File is too large to view")
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            raise ToolError("File is not text") from None
        start = max(int(args.get("start_line") or 1), 1)
        end = int(args.get("end_line") or len(lines))
        return "\n".join(
            f"{n}. {lines[n - 1]}" for n in range(start, min(end, len(lines)) + 1)
        )

    def _files(self, base: Path, pattern: str | None):
        if base.is_file():
            yield base
            return
        for path in sorted(base.rglob("*")):
            if (
                path.is_file()
                and self._inside(path)
                and (pattern is None or path.match(pattern))
            ):
                yield path

    def _grep(self, args: dict) -> str:
        regex = re.compile(str(args.get("pattern") or ""))
        pattern = str(args["glob"]) if args.get("glob") else None
        results: list[str] = []
        for path in self._files(self._resolve(args.get("path")), pattern):
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                lines = path.read_text().splitlines()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(lines, 1):
                if regex.search(line):
                    results.append(f"{self._rel(path)}:{n}:{line[:300]}")
                    if len(results) >= MAX_RESULTS:
                        return "\n".join(results) + "\n[more results omitted]"
        return "\n".join(results) or "No matches"

    def _glob(self, args: dict) -> str:
        pattern = str(args.get("pattern") or "")
        if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ToolError("Use a relative pattern without '..'")
        found = [
            self._rel(p) for p in sorted(self.root.glob(pattern)) if self._inside(p)
        ]
        return "\n".join(found[:MAX_RESULTS]) or "No files found"
