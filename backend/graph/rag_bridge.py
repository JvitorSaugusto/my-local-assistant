"""Ponte entre o agente (backend.graph) e o RAG.

É o ÚNICO arquivo de backend.graph que conhece backend.rag, e só importa dentro das
funções: se o RAG não estiver instalado, configurado ou o Postgres cair, o agente
continua funcionando normalmente (as funções devolvem texto vazio / mensagem clara).
"""

from __future__ import annotations

import time

_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
_CACHE_TTL = 300.0
_CACHE_MAX = 32
_OFF_SECONDS = 60.0
_off_until = 0.0


async def rag_context(workspace: str | None, query: str, limit: int = 6, max_chars: int = 6000) -> str:
    """Trechos relacionados à consulta, prontos para o dossiê. Vazio se não houver índice."""
    global _off_until
    query = (query or "").strip()
    now = time.monotonic()
    if not workspace or not query or now < _off_until:
        return ""

    key = (workspace, query[:400])
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        from backend.rag import get_service

        text = await get_service().context_for_workspace(workspace, query, limit=limit, max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001
        print(f"ℹ️ [RAG] contexto indisponível (seguindo sem ele): {exc}")
        _off_until = time.monotonic() + _OFF_SECONDS
        return ""

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.monotonic(), text)
    return text


async def rag_search_for_tool(
    workspace: str | None, query: str, path_prefix: str | None = None, limit: int = 6
) -> str:
    """Resposta da tool search_codebase (mensagens de erro claras para o modelo)."""
    if not workspace:
        return "ERRO: o workspace não está definido."
    if not (query or "").strip():
        return "ERRO: informe o que buscar."
    try:
        from backend.rag import get_service
        from backend.rag.search import format_hits

        service = get_service()
        source = await service.find_source_for_workspace(workspace)
        if not source:
            return (
                "Este workspace ainda não foi indexado no RAG. Use search_in_file e generate_repo_map, "
                "ou peça ao usuário para indexá-lo em /static/rag.html."
            )
        hits = await service.search(query, source_id=source["id"], limit=limit, path_prefix=path_prefix)
        return format_hits(hits)
    except Exception as exc:  # noqa: BLE001
        return f"ERRO ao consultar o RAG: {exc}"
