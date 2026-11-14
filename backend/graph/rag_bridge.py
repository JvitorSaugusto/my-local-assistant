"""Ponte entre o agente (backend.graph) e o RAG.

É o ÚNICO arquivo de backend.graph que conhece backend.rag, e só importa dentro das
funções: se o RAG não estiver instalado, configurado ou o Postgres cair, o agente
continua funcionando normalmente (as funções devolvem texto vazio / mensagem clara).
"""

from __future__ import annotations

import asyncio
import time

_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
_CACHE_TTL = 300.0
_CACHE_MAX = 32
_OFF_SECONDS = 60.0
_off_until = 0.0

# A atualização do índice não pode rodar a cada consulta: no máximo 1x por intervalo
# e sem bloquear o agente além do timeout (ela continua em segundo plano).
_REFRESH_EVERY = 120.0
_REFRESH_TIMEOUT = 8.0
_last_refresh: dict[str, float] = {}


def _swallow(task) -> None:
    if not task.cancelled():
        task.exception()


async def _refresh_throttled(service, workspace: str):
    now = time.monotonic()
    if now - _last_refresh.get(workspace, -1e9) < _REFRESH_EVERY:
        return None
    _last_refresh[workspace] = now
    task = asyncio.ensure_future(service.refresh_workspace(workspace))
    task.add_done_callback(_swallow)
    try:
        refreshed = await asyncio.wait_for(asyncio.shield(task), timeout=_REFRESH_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"ℹ️ [RAG] atualização do índice passou de {_REFRESH_TIMEOUT:.0f}s; seguindo com o índice atual.")
        return None
    if refreshed and (refreshed.get("files_indexed") or refreshed.get("files_removed")):
        _CACHE.clear()
    return refreshed


async def rag_context(workspace: str | None, query: str, limit: int = 6, max_chars: int = 6000) -> str:
    """Fontes disponíveis + trechos do escopo padrão do projeto, para o dossiê. Vazio se nada foi indexado."""
    global _off_until
    query = (query or "").strip()
    if not workspace or not query or time.monotonic() < _off_until:
        return ""

    try:
        from backend.rag import get_service

        service = get_service()
        await _refresh_throttled(service, workspace)

        key = (workspace, query[:400])
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return cached[1]

        hits_text = await service.context_for_workspace(workspace, query, limit=limit, max_chars=max_chars)
        overview = await service.overview(workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"ℹ️ [RAG] contexto indisponível (seguindo sem ele): {exc}")
        _off_until = time.monotonic() + _OFF_SECONDS
        return ""

    parts = []
    if overview:
        parts.append('Fontes indexadas (para consultar outra, use search_codebase com source="nome"):\n' + overview)
    if hits_text:
        parts.append(hits_text)
    text = "\n\n".join(parts)

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.monotonic(), text)
    return text


async def rag_search_for_tool(
    workspace: str | None, query: str, path_prefix: str | None = None, limit: int = 6, source: str | None = None
) -> str:
    """Resposta da tool search_codebase. `source`: vazio = projeto + vinculadas, 'all' = todas, ou o nome de uma fonte."""
    if not (query or "").strip():
        return "ERRO: informe o que buscar."
    try:
        from backend.rag import get_service
        from backend.rag.search import format_hits

        service = get_service()
        if workspace:
            await _refresh_throttled(service, workspace)
        hits, label, sources = await service.search_scoped(query, workspace, source, limit, path_prefix)
        if not sources:
            overview = await service.overview(workspace)
            if overview:
                return (
                    "Nenhuma fonte é consultada por padrão para este workspace. Fontes disponíveis:\n"
                    f'{overview}\nRefaça a busca com source="nome" ou source="all".'
                )
            return (
                "Nada foi indexado no RAG ainda. Use search_in_file e generate_repo_map, "
                "ou peça ao usuário para indexar em /static/rag.html."
            )
        names = ", ".join(s["name"] for s in sources)
        return f"Consultado: {label} ({names})\n\n" + format_hits(hits)
    except Exception as exc:  # noqa: BLE001
        return f"ERRO ao consultar o RAG: {exc}"
