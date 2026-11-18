"""Atalho determinístico para pedidos de mapa/estrutura do projeto nos modos Normal e Code (sem LLM).

O mapa sai direto do disco (render_project_tree), então nunca é inventado. Se não há projeto selecionado, avisa isso
em vez de deixar o modelo improvisar um mapa a partir de mensagens antigas. Só dispara para mensagens curtas que
pedem mapa/árvore/estrutura E citam repositório, projeto, pasta, diretório, arquivos ou código.
"""
from __future__ import annotations

import re
from pathlib import Path

_MAP_INTENT = re.compile(
    r"\b(mapa|[áa]rvore|tree|estrutura\s+(?:de\s+)?(?:pastas?|diret[óo]rios?|arquivos?|projeto))\b", re.IGNORECASE
)
_TASK_WORD = re.compile(r"\b(tasks?|tarefas?)\b", re.IGNORECASE)
_REPO_WORD = re.compile(
    r"\b(reposit[óo]rio|repo|projeto|pastas?|diret[óo]rios?|workspace|estrutura|arquivos|c[óo]digo)\b", re.IGNORECASE
)
_SKIP_DIRS = {"__pycache__", "node_modules", "venv", "env", "dist", "build", "out", "site-packages", "coverage", "htmlcov", "target", "staticfiles"}
MAX_CHARS = 300
NO_PROJECT = ("Nenhum projeto está selecionado nesta conversa (ou a pasta escolhida não existe mais), então não tenho de onde "
              "ler o mapa e não vou inventar um. Escolha o projeto na aba **Projeto** e peça de novo.")


def wants_repo_map(text: str) -> bool:
    text = str(text or "")
    return (len(text) <= MAX_CHARS and bool(_MAP_INTENT.search(text)) and not _TASK_WORD.search(text)
            and bool(_REPO_WORD.search(text)))


def _mentions(name: str, text: str) -> bool:
    return bool(name) and re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text.lower()) is not None


def _subdirs(directory: Path) -> list[Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda e: e.name.lower())
    except OSError:
        return []
    return [e for e in entries if e.is_dir() and not e.name.startswith(".") and e.name not in _SKIP_DIRS]


def pick_target(root: Path, text: str, max_depth: int = 3) -> Path:
    """Pasta citada no pedido (a mais funda, até 3 níveis); sem citação, a raiz do projeto."""
    best: tuple[int, Path] | None = None

    def scan(directory: Path, depth: int) -> None:
        nonlocal best
        for entry in _subdirs(directory):
            if _mentions(entry.name, text) and (best is None or depth > best[0]):
                best = (depth, entry)
            if depth + 1 < max_depth:
                scan(entry, depth + 1)

    scan(root, 0)
    return best[1] if best else root


def build_map_text(workspace: str, text: str, render) -> str | None:
    """None se o pedido não é de mapa. Senão o texto da resposta. `render(Path) -> str` desenha a árvore."""
    if not wants_repo_map(text):
        return None
    folder = str(workspace or "").strip()
    root = Path(folder) if folder and folder != "Diretório não informado" else None
    if root is None or not root.is_dir():
        return NO_PROJECT
    target = pick_target(root, text)
    tree = render(target)
    if not tree:
        return f"A pasta `{target}` está vazia ou não pôde ser lida."
    return (f"Mapa de `{target.name or target}` montado direto do disco, sem IA e sem nada inventado "
            "(.git, venv, node_modules e caches ficam de fora):\n\n```\n" + tree + "\n```\n\n"
            "Para ver o detalhe de uma pasta, peça por exemplo \"mapa da pasta backend\". "
            "Para saber o que cada arquivo faz, use @heavy.")


def project_map_message(state, tag: str):
    """AIMessage pronta para o nó devolver, ou None se a última mensagem não é um pedido de mapa."""
    from langchain_core.messages import AIMessage

    from .node_helpers import now_iso, render_project_tree

    messages = state.get("messages") or []
    if not messages or getattr(messages[-1], "type", "") != "human":
        return None
    content = messages[-1].content
    if isinstance(content, list):
        content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    reply = build_map_text(state.get("workspace_path"), str(content or ""), render_project_tree)
    if reply is None:
        return None
    return AIMessage(content=reply, name="Mapa do projeto", additional_kwargs={"message_tag": tag, "created_at": now_iso()})
