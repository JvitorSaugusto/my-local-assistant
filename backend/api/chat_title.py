"""Título automático do chat: depois da 1ª resposta, troca 'Nova conversa' por um título curto (3 a 6 palavras)."""

from __future__ import annotations

import asyncio
import re

DEFAULT_TITLES = ("", "nova conversa", "novo chat", "new chat")
_TAG = re.compile(r"^(?:@\w+\s*)+")
_THINK = re.compile(r"<think>.*?</think>", re.S)
_BG: set = set()


def clean_title(raw: str) -> str:
    text = _THINK.sub("", raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    text = re.sub(r"^[#>*\-\s\"'“”`]+|[\"'“”`*.\s]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:60].rstrip()


def fallback_title(user_text: str) -> str:
    text = _TAG.sub("", (user_text or "").strip()).split("[Arquivos anexados]")[0]
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    title = " ".join(w for w in words[:6] if w)
    return (title[:60].rstrip() or "Nova conversa")


async def _generate(user_text: str, answer: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.graph.config import standard_llm

    prompt = (
        "Crie um título curto para esta conversa: 3 a 6 palavras, em português, sem aspas, sem ponto final, "
        "que descreva o assunto. Responda só com o título."
    )
    body = f"Pergunta: {_TAG.sub('', user_text or '').strip()[:800]}\n\nResposta: {(answer or '')[:600]}"
    response = await asyncio.wait_for(standard_llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=body)]), timeout=30)
    content = response.content if isinstance(response.content, str) else str(response.content)
    return clean_title(content)


async def maybe_title_chat(thread_id: str, user_text: str, answer: str) -> str | None:
    """Só renomeia se o chat ainda tem o título padrão. Nunca levanta."""
    try:
        from sqlalchemy import select, update

        from backend.database.config import async_session_env
        from backend.database.models import AiChatModel

        async with async_session_env() as db:
            current = (await db.execute(select(AiChatModel.title).where(AiChatModel.thread_id == thread_id))).scalar_one_or_none()
        if current is None or (current or "").strip().lower() not in DEFAULT_TITLES:
            return None
        try:
            title = await _generate(user_text, answer)
        except Exception:
            title = ""
        if len(title) < 3:
            title = fallback_title(user_text)
        if title.lower() in DEFAULT_TITLES:
            return None
        async with async_session_env() as db:
            await db.execute(
                update(AiChatModel)
                .where(AiChatModel.thread_id == thread_id, AiChatModel.title == current)
                .values(title=title)
            )
            await db.commit()
        return title
    except Exception as exc:
        print(f"[💬 CHAT] não consegui titular o chat ({type(exc).__name__}: {exc})")
        return None


def schedule_title(thread_id: str, user_text: str, answer: str) -> None:
    """Dispara em segundo plano (não atrasa a resposta)."""
    task = asyncio.create_task(maybe_title_chat(thread_id, user_text, answer))
    _BG.add(task)
    task.add_done_callback(_BG.discard)
