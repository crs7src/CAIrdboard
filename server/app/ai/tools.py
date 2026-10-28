"""Read-only repo tools (view, grep, glob) for providers that have no built-in ones.

Everything is confined to the repo: paths are resolved (symlinks included) and must
stay inside it. Nothing can write, delete or run commands.
"""

import re
from pathlib import Path

MAX_OUTPUT_CHARS = 30_000
MAX_FILE_BYTES = 1_000_000
MAX_RESULTS = 200
MAX_ITERATIONS = 20
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


class ToolError(Exception):
    pass


def _cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n[output truncated]"


class ToolBox:
    def __init__(self, repo: str):
        self.root = Path(repo).resolve()

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
