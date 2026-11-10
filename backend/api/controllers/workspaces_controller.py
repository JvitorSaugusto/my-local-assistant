"""Navegador de pastas do servidor (para escolher o workspace de qualquer dispositivo).

Só lista PASTAS, e somente dentro das raízes permitidas:
- WORKSPACE_ROOTS no .env (várias separadas por ';' ou ','), ou
- por padrão, a pasta que contém o repositório do assistente (onde ficam seus outros projetos).
"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

workspaces_router = APIRouter()

_HIDDEN = {"node_modules", "__pycache__", "venv", ".venv", "env", "dist", "build", "$RECYCLE.BIN",
           "System Volume Information"}


def _roots() -> list[Path]:
    raw = os.getenv("WORKSPACE_ROOTS", "")
    items = [item.strip().strip('"') for item in raw.replace(";", ",").split(",") if item.strip()]
    roots = [Path(item).expanduser() for item in items]
    if not roots:
        # este arquivo: <repo>/backend/api/controllers/workspaces_controller.py
        roots = [Path(__file__).resolve().parents[3].parent]
    resolved = []
    for root in roots:
        try:
            if root.is_dir():
                resolved.append(root.resolve())
        except OSError:
            continue
    return resolved


def _root_of(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        if path == root or root in path.parents:
            return root
    return None


def _entry(path: Path) -> dict:
    try:
        is_repo = (path / ".git").exists()
    except OSError:
        is_repo = False
    return {"name": path.name or str(path), "path": str(path), "is_repo": is_repo}


@workspaces_router.get("/browse")
def browse(path: str = Query("", description="Pasta a listar; vazio = raízes permitidas")):
    roots = _roots()
    if not roots:
        raise HTTPException(status_code=404, detail="Nenhuma pasta raiz válida. Defina WORKSPACE_ROOTS no .env.")

    if not path.strip():
        return {"path": "", "parent": None, "roots": True, "dirs": [_entry(root) for root in roots]}

    try:
        target = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=400, detail="Caminho inválido.")

    root = _root_of(target, roots)
    if root is None:
        raise HTTPException(status_code=403, detail="Pasta fora das raízes permitidas.")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Pasta não encontrada.")

    dirs = []
    try:
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if child.name.startswith(".") or child.name in _HIDDEN:
                continue
            try:
                if child.is_dir():
                    dirs.append(_entry(child))
            except OSError:
                continue
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Sem acesso à pasta: {exc}")

    return {"path": str(target), "parent": "" if target == root else str(target.parent), "roots": False, "dirs": dirs}
