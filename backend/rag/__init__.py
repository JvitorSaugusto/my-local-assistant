"""RAG de código: módulo ISOLADO (não importa nada de backend.graph nem backend.api).

O resto do sistema só deve usar:
    from backend.rag import get_service, rag_startup
Importações são preguiçosas para que este pacote carregue mesmo sem SQLAlchemy.
"""

from __future__ import annotations

__all__ = ["get_service", "rag_startup"]


def get_service():
    from .service import get_service as _get_service

    return _get_service()


async def rag_startup() -> bool:
    """Prepara o schema. Nunca levanta: se falhar, o RAG fica indisponível e o app segue."""
    try:
        return await get_service().startup()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ [RAG] indisponível: {exc}")
        return False
