"""Upload de anexos do chat para uma pasta controlada do workspace.

Os arquivos vão para `<workspace>/.assistant_uploads/<thread_id>/`, com limite de
tamanho, extensões permitidas, nome sanitizado e sem sobrescrever nada existente.
Módulo sem dependências de FastAPI para poder ser testado isoladamente.
"""

import os
import re
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable

UPLOAD_DIR_NAME = ".assistant_uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_THREAD = 50
CHUNK_SIZE = 64 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}
ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".py", ".json", ".csv", ".pdf", ".docx", ".svg", ".zip", *IMAGE_EXTENSIONS,
}
TEXT_EXTENSIONS = {".md", ".txt", ".py", ".json", ".csv", ".svg"}


def max_bytes_for(ext: str) -> int:
    return MAX_ZIP_BYTES if ext == ".zip" else MAX_UPLOAD_BYTES

_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class UploadError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def sanitize_thread_id(thread_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", thread_id or "").strip("_")[:80]
    if not cleaned:
        raise UploadError("thread_id inválido.")
    return cleaned


def sanitize_filename(filename: str) -> tuple[str, str]:
    """Devolve (nome_sem_extensão, extensão_minúscula) já saneados ou levanta UploadError."""
    base = (filename or "").replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKC", base)
    base = "".join(ch for ch in base if ch.isprintable())
    base = base.strip().lstrip(".")

    stem, dot, ext = base.rpartition(".")
    if not dot:
        raise UploadError("O arquivo precisa ter extensão.")
    ext = "." + ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadError(f"Extensão '{ext}' não permitida. Permitidas: {allowed}.", 415)

    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._")[:100] or "arquivo"
    if stem.lower() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    return stem, ext


def _validate_first_chunk(ext: str, chunk: bytes) -> None:
    if ext == ".pdf" and not chunk.startswith(b"%PDF-"):
        raise UploadError("O arquivo não parece ser um PDF válido.", 415)
    if ext == ".docx" and not chunk.startswith(b"PK\x03\x04"):
        raise UploadError("O arquivo não parece ser um DOCX válido.", 415)
    if ext == ".zip" and not (chunk.startswith(b"PK\x03\x04") or chunk.startswith(b"PK\x05\x06")):
        raise UploadError("O arquivo não parece ser um ZIP válido.", 415)
    magic = {
        ".png": (b"\x89PNG",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".gif": (b"GIF87a", b"GIF89a"),
        ".webp": (b"RIFF",),
        ".ico": (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"),
    }.get(ext)
    if magic and not chunk.startswith(magic):
        raise UploadError(f"O arquivo não parece ser uma imagem {ext} válida.", 415)
    if ext in TEXT_EXTENSIONS and b"\x00" in chunk:
        raise UploadError("O arquivo contém dados binários, mas a extensão é de texto.", 415)


def _ensure_git_exclude(root: Path) -> None:
    """Evita que a pasta de uploads suje o `git status` (melhor esforço)."""
    try:
        git_dir = root / ".git"
        if not git_dir.is_dir():
            return
        exclude = git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{UPLOAD_DIR_NAME}/"
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if entry not in current.splitlines():
            prefix = "" if not current or current.endswith("\n") else "\n"
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(f"{prefix}{entry}\n")
    except OSError:
        pass


def _prepare_target_dir(workspace_path: str, thread_id: str) -> tuple[Path, Path]:
    if not workspace_path or not workspace_path.strip():
        raise UploadError("Defina um diretório de trabalho antes de anexar arquivos.")
    root = Path(workspace_path.strip()).resolve()
    if not root.is_dir():
        raise UploadError("O diretório de trabalho não existe.")

    target = root / UPLOAD_DIR_NAME / sanitize_thread_id(thread_id)
    target.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(root)
    except ValueError:
        raise UploadError("Pasta de uploads fora do workspace.", 400)
    return root, target.resolve()


async def save_upload(
    workspace_path: str,
    thread_id: str,
    filename: str,
    read_chunk: Callable[[int], Awaitable[bytes]],
) -> dict:
    """Grava o upload e devolve {path (relativo, com '/'), name, size}."""
    stem, ext = sanitize_filename(filename)
    root, target = _prepare_target_dir(workspace_path, thread_id)

    existing = [p for p in target.iterdir() if p.is_file()]
    if len(existing) >= MAX_FILES_PER_THREAD:
        raise UploadError(f"Limite de {MAX_FILES_PER_THREAD} anexos por conversa atingido.", 409)

    limit = max_bytes_for(ext)
    first = await read_chunk(CHUNK_SIZE)
    if not first:
        raise UploadError("Arquivo vazio.")
    _validate_first_chunk(ext, first)

    handle = None
    final_path = None
    for index in range(0, 1000):
        name = f"{stem}{ext}" if index == 0 else f"{stem}-{index}{ext}"
        candidate = target / name
        try:
            handle = open(candidate, "xb")  # 'x': nunca sobrescreve
            final_path = candidate
            break
        except FileExistsError:
            continue
    if handle is None or final_path is None:
        raise UploadError("Não foi possível escolher um nome livre para o arquivo.", 409)

    size = 0
    try:
        with handle:
            chunk = first
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise UploadError(
                        f"Arquivo maior que o limite de {limit // (1024 * 1024)} MB.", 413
                    )
                handle.write(chunk)
                chunk = await read_chunk(CHUNK_SIZE)
    except BaseException:
        try:
            os.remove(final_path)
        except OSError:
            pass
        raise

    _ensure_git_exclude(root)
    return {
        "path": final_path.relative_to(root).as_posix(),
        "name": final_path.name,
        "size": size,
    }


def list_uploads(workspace_path: str, thread_id: str) -> list[dict]:
    """Anexos já enviados desta conversa: [{name, path, size}] (mais recentes primeiro)."""
    if not workspace_path or not workspace_path.strip():
        raise UploadError("Defina um diretório de trabalho antes de listar anexos.")
    root = Path(workspace_path.strip()).resolve()
    if not root.is_dir():
        raise UploadError("O diretório de trabalho não existe.")
    folder = root / UPLOAD_DIR_NAME / sanitize_thread_id(thread_id)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and not p.is_symlink()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": p.name, "path": p.relative_to(root).as_posix(), "size": p.stat().st_size}
        for p in files
    ]


def find_upload(workspace_path: str, thread_id: str | None, source: str) -> tuple[Path | None, str | None]:
    """Resolve o NOME de um anexo desta conversa. Devolve (arquivo, None) ou (None, erro)."""
    if not thread_id:
        return None, "ERRO: esta execução não tem conversa associada, então não há anexos."
    root = Path(workspace_path).resolve()
    try:
        folder = (root / UPLOAD_DIR_NAME / sanitize_thread_id(thread_id)).resolve()
        folder.relative_to(root)
    except (UploadError, ValueError):
        return None, "ERRO: pasta de anexos inválida."

    name = (source or "").replace("\\", "/").split("/")[-1].strip()
    available = (
        sorted(p.name for p in folder.iterdir() if p.is_file() and not p.is_symlink())
        if folder.is_dir() else []
    )
    match = next((n for n in available if n == name), None) or next(
        (n for n in available if n.lower() == name.lower()), None
    )
    if not match:
        shown = ", ".join(available) if available else "nenhum anexo enviado nesta conversa"
        return None, f"ERRO: anexo '{source}' não encontrado. Anexos disponíveis: {shown}."
    return folder / match, None
