"""Busca híbrida: vetor + texto + símbolo, combinadas por Reciprocal Rank Fusion."""

from __future__ import annotations

import asyncio
import re

from .entities import SearchHit
from .providers import Embedder
from .store_base import VectorStore

_WORD = re.compile(r"[A-Za-z0-9]+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{3,}")
STOP = {"para", "como", "qual", "quais", "onde", "esta", "este", "isso", "sobre", "with", "that", "this", "from", "the"}


def text_tokens(query: str, limit: int = 12) -> list[str]:
    seen: list[str] = []
    for word in _WORD.findall(query.lower()):
        if len(word) >= 2 and word not in STOP and word not in seen:
            seen.append(word)
    return seen[:limit]


def symbol_tokens(query: str, limit: int = 4) -> list[str]:
    seen: list[str] = []
    for word in _IDENT.findall(query):
        if word.lower() not in STOP and word not in seen:
            seen.append(word)
    return seen[:limit]


def fuse(rankings: list[list[SearchHit]], k: int = 60) -> list[SearchHit]:
    merged: dict[int, SearchHit] = {}
    for ranking in rankings:
        for position, hit in enumerate(ranking, start=1):
            current = merged.get(hit.chunk_id)
            if current is None:
                hit.score = 0.0
                merged[hit.chunk_id] = current = hit
            current.score += 1.0 / (k + position)
            for tag in hit.matched_by:
                if tag not in current.matched_by:
                    current.matched_by.append(tag)
    return sorted(merged.values(), key=lambda h: -h.score)


async def hybrid_search(
    store: VectorStore,
    embedder: Embedder,
    query: str,
    source_ids: list[int],
    limit: int = 8,
    path_prefix: str | None = None,
) -> list[SearchHit]:
    if not source_ids or not query.strip():
        return []
    pool = max(limit * 3, 20)
    vector = (await asyncio.to_thread(embedder.embed, [query]))[0]
    rankings = [await store.search_vector(source_ids, vector, pool, path_prefix)]
    tokens = text_tokens(query)
    if tokens:
        rankings.append(await store.search_text(source_ids, tokens, pool, path_prefix))
    symbols = symbol_tokens(query)
    if symbols:
        rankings.append(await store.search_symbol(source_ids, symbols, pool, path_prefix))
    return fuse(rankings)[:limit]


def format_hits(hits: list[SearchHit], max_chars: int = 6000, snippet_chars: int = 1200) -> str:
    """Texto pronto para o agente: etiqueta + resumo + trecho de cada resultado."""
    if not hits:
        return "Nenhum trecho encontrado no índice."
    blocks: list[str] = []
    used = 0
    for number, hit in enumerate(hits, start=1):
        code = hit.content if len(hit.content) <= snippet_chars else hit.content[:snippet_chars] + "\n[... trecho cortado; use read_file_chunk ...]"
        block = (
            f"#{number} {hit.path}:{hit.start_line}-{hit.end_line} [{hit.kind}] {hit.qualname}\n"
            f"resumo: {hit.summary or '-'}\n<<<CÓDIGO>>>\n{code}\n<<<FIM>>>"
        )
        if used + len(block) > max_chars and blocks:
            blocks.append(f"[... mais {len(hits) - number + 1} resultado(s) omitidos pelo limite de tamanho ...]")
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)
