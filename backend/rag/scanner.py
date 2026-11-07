"""Varredura do repositório: lista arquivos de texto relevantes com hash de conteúdo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .entities import FileInfo, sha1_text

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build", ".idea",
    ".vscode", ".next", "coverage", "site-packages", ".rag_work",
}
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".html": "html", ".css": "css",
    ".md": "markdown", ".txt": "text", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".sh": "shell", ".bat": "batch", ".json": "json",
}
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock"}
JSON_MAX_BYTES = 100_000


def _ignored(rel: str) -> bool:
    parts = rel.split("/")
    for part in parts[:-1]:
        if part in IGNORE_DIRS:
            return True
    name = parts[-1]
    return name in SKIP_NAMES or name == ".env" or name.startswith(".env.") or name.endswith(".min.js")


def _git_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "-c", "-o", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return [p for p in result.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            found.append(rel)
    return found


def list_candidate_files(root: str | Path) -> list[str]:
    """Respeita o .gitignore quando é um repositório git; senão percorre as pastas."""
    base = Path(root).resolve()
    names = _git_files(base)
    if names is None:
        names = _walk_files(base)
    return sorted({n.replace("\\", "/") for n in names if not _ignored(n.replace("\\", "/"))})


def scan(root: str | Path, max_file_bytes: int = 400_000) -> tuple[list[FileInfo], dict[str, int]]:
    """(arquivos, contagem de ignorados por motivo)."""
    base = Path(root).resolve()
    files: list[FileInfo] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for rel in list_candidate_files(base):
        suffix = Path(rel).suffix.lower()
        language = LANGUAGES.get(suffix)
        if not language:
            skip("extensão não suportada")
            continue
        path = base / rel
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size == 0:
                skip("vazio")
                continue
            if size > max_file_bytes or (language == "json" and size > JSON_MAX_BYTES):
                skip("grande demais")
                continue
            raw = path.read_bytes()
        except OSError:
            skip("ilegível")
            continue
        if b"\x00" in raw[:4096]:
            skip("binário")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        files.append(FileInfo(rel, str(path), size, sha1_text(text.replace("\r\n", "\n")), language))
    return files, skipped


def read_text(abs_path: str) -> str:
    raw = Path(abs_path).read_bytes()
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
