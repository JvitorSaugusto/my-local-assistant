"""Configuração do módulo RAG (variáveis de ambiente). Não importa nada do resto do projeto."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RagConfig:
    database_url: str
    ollama_url: str
    embed_model: str
    embed_dim: int
    summary_model: str  # vazio = resumo heurístico (rápido, sem LLM)
    summary_think: str
    summary_timeout: float
    summary_concurrency: int
    embed_batch: int
    max_file_bytes: int
    max_chunk_lines: int
    zip_max_bytes: int
    zip_max_files: int
    work_dir: str


def load_config() -> RagConfig:
    url = os.getenv("RAG_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    return RagConfig(
        database_url=url,
        ollama_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        embed_model=os.getenv("RAG_EMBED_MODEL", "nomic-embed-text"),
        embed_dim=int(os.getenv("RAG_EMBED_DIM", "768")),
        summary_model=os.getenv("RAG_SUMMARY_MODEL", "").strip(),
        summary_think=os.getenv("RAG_SUMMARY_THINK", "").strip(),
        summary_timeout=float(os.getenv("RAG_SUMMARY_TIMEOUT", "180")),
        summary_concurrency=int(os.getenv("RAG_SUMMARY_CONCURRENCY", "2")),
        embed_batch=int(os.getenv("RAG_EMBED_BATCH", "16")),
        max_file_bytes=int(os.getenv("RAG_MAX_FILE_BYTES", "400000")),
        max_chunk_lines=int(os.getenv("RAG_MAX_CHUNK_LINES", "200")),
        zip_max_bytes=int(os.getenv("RAG_ZIP_MAX_BYTES", str(500 * 1024 * 1024))),
        zip_max_files=int(os.getenv("RAG_ZIP_MAX_FILES", "20000")),
        work_dir=os.getenv("RAG_WORK_DIR", ".rag_work"),
    )
