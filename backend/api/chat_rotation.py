"""Chat cheio -> continua em um chat NOVO, que já nasce com um resumo do que aconteceu (estratégia do ChatGPT).

Regras:
- Só rotaciona DEPOIS que o trabalho do chat terminou: nenhuma execução do grafo ativa e nenhuma task em
  'queued'/'running' neste chat. Enquanto houver, o chat continua normalmente e a resposta traz chat_full=true.
- O chat novo tem o MESMO nome do anterior com um número na frente ("2 - Nome", "3 - Nome"...).
- O chat novo recebe: resumo (LLM com fallback simples) + lista das tasks, o projeto/fontes fixados (chat_pins) e
  as tasks em aberto (pending/failed/review), que são movidas para ele (o dispatch filtra por thread).
- O chat antigo recebe um aviso com marcador (additional_kwargs["chat_handoff"]); mensagens seguintes nele só
  repetem o aviso, sem criar outro chat.

Configuração (.env): CHAT_ROTATE_MAX_TOKENS (padrão 120000; 0 desliga), CHAT_ROTATE_MAX_MESSAGES (padrão 0 = desligado),
CHAT_HANDOFF_MAX_CHARS (padrão 3500), CHAT_HANDOFF_TIMEOUT (segundos do LLM do resumo, padrão 120).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.graph.handoff import edited_files, join_handoff, plain_summary

HANDOFF_TAG = "chat_handoff"
ACTIVE_STATUSES = ("queued", "running")
OPEN_STATUSES = ("pending", "failed", "review")
UPLOAD_OPS = ("copy_upload", "extract_zip")

_TITLE_PREFIX = re.compile(r"^\s*(\d{1,3})\s*[-–—.)]\s+(\S.*)$", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)
_lock: asyncio.Lock | None = None

HANDOFF_PROMPT = (
    "Você prepara a PASSAGEM DE BASTÃO de uma conversa longa entre um usuário e um assistente de programação "
    "para um chat novo. Escreva em português, direto, em tópicos curtos (no máximo ~300 palavras), com as seções:\n"
    "- Objetivo e projeto (o que o usuário está construindo ou corrigindo)\n"
    "- O que já foi feito e decidido (inclua nomes de arquivos, funções e valores citados)\n"
    "- Pendências e próximo passo\n"
    "- Preferências e regras combinadas com o usuário\n"
    "Use SOMENTE o que está no material; não invente nada. Não liste as tasks (elas são anexadas à parte). "
    "Responda apenas com o resumo."
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def max_tokens() -> int:
    return _env_int("CHAT_ROTATE_MAX_TOKENS", 120000)


def max_messages() -> int:
    return _env_int("CHAT_ROTATE_MAX_MESSAGES", 0)


def max_handoff_chars() -> int:
    return max(800, _env_int("CHAT_HANDOFF_MAX_CHARS", 3500))


def _log(message: str) -> None:
    print(f"[💬 CHAT] {message}")


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _now() -> str:
    try:
        from backend.graph.node_helpers import now_iso

        return now_iso()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Funções puras (sem banco e sem LLM)
# ----------------------------------------------------------------------

def next_title(title: str | None) -> str:
    """'Nome' -> '2 - Nome'; '2 - Nome' -> '3 - Nome'. O número fica na frente; o nome é o mesmo."""
    base = (title or "").strip() or "Novo chat"
    number = 1
    match = _TITLE_PREFIX.match(base)
    if match:
        number = int(match.group(1))
        base = match.group(2).strip()
    return f"{number + 1} - {base}"[:255]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts)
    return str(content or "")


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _one_line(text: str | None, limit: int) -> str:
    return _clip(re.sub(r"\s+", " ", text or "").strip(), limit)


def message_chars(message: Any) -> int:
    total = len(_text_of(getattr(message, "content", "")))
    for call in getattr(message, "tool_calls", None) or []:
        try:
            total += len(json.dumps(call.get("args") or {}, ensure_ascii=False))
        except Exception:
            pass
    return total


def chat_tokens(messages: list[Any], summary: str = "") -> int:
    """Tamanho estimado do chat em tokens (~3 caracteres por token, estimativa conservadora)."""
    return (sum(message_chars(m) for m in messages) + len(summary or "")) // 3


def count_turns(messages: list[Any]) -> int:
    """Mensagens 'de conversa' (usuário e respostas finais), sem tool calls e sem resultados de ferramenta."""
    return sum(
        1
        for m in messages
        if getattr(m, "type", "") in ("human", "ai") and not (m.type == "ai" and getattr(m, "tool_calls", None))
    )


def is_full(tokens: int, turns: int) -> bool:
    limit_tokens, limit_messages = max_tokens(), max_messages()
    if limit_tokens > 0 and tokens >= limit_tokens:
        return True
    return limit_messages > 0 and turns >= limit_messages


def find_handoff(messages: list[Any]) -> dict | None:
    """Marcador de que este chat já foi rotacionado (fica no aviso, última mensagem do chat antigo)."""
    if not messages:
        return None
    marker = (getattr(messages[-1], "additional_kwargs", None) or {}).get(HANDOFF_TAG)
    return marker if isinstance(marker, dict) and marker.get("thread_id") else None


def meaningful_messages(messages: list[Any]) -> list[tuple[str, str]]:
    """[(papel, texto)] só do que é conversa de verdade (sem tools e sem avisos internos do sistema)."""
    out: list[tuple[str, str]] = []
    for m in messages:
        kind = getattr(m, "type", "")
        if kind not in ("human", "ai") or (kind == "ai" and getattr(m, "tool_calls", None)):
            continue
        tag = str((getattr(m, "additional_kwargs", None) or {}).get("message_tag") or "")
        if tag.startswith("internal_") or tag.startswith("chat_handoff"):
            continue
        text = _text_of(getattr(m, "content", "")).strip()
        if text:
            out.append((kind, text))
    return out


def build_transcript(pairs: list[tuple[str, str]], max_messages_: int = 24, per_message: int = 1500, total: int = 20000) -> str:
    chunks = [
        f"[{'Usuário' if role == 'human' else 'Assistente'}] {_clip(text, per_message)}"
        for role, text in pairs[-max_messages_:]
    ]
    kept: list[str] = []
    used = 0
    for chunk in reversed(chunks):  # prioriza o mais recente
        if kept and used + len(chunk) > total:
            break
        kept.append(chunk)
        used += len(chunk) + 2
    return "\n\n".join(reversed(kept))


def tasks_block(tasks: list[dict]) -> str:
    """Parte DETERMINÍSTICA do resumo: tasks em aberto (com último erro) e contagem das concluídas."""
    lines: list[str] = []
    open_tasks = [t for t in tasks if t["status"] in OPEN_STATUSES]
    done = [t for t in tasks if t["status"] == "completed"]
    if open_tasks:
        lines.append("Tasks em aberto (movidas para este chat):")
        for t in open_tasks[:30]:
            line = f"- #{t['id']} [{t['status']}] {_one_line(t['title'], 110)}"
            if t["status"] in ("failed", "review") and t.get("error"):
                line += f" | último aviso: {_one_line(t['error'], 200)}"
            if t.get("uploads"):
                line += f" | usa anexo(s): {', '.join(t['uploads'])} (copiados para este chat)"
            lines.append(line)
        if len(open_tasks) > 30:
            lines.append(f"- ... e mais {len(open_tasks) - 30} task(s).")
    if done:
        last = ", ".join(f"#{t['id']}" for t in done[-8:])
        lines.append(f"Tasks concluídas no chat anterior: {len(done)} (últimas: {last}).")
    return "\n".join(lines)


def fallback_summary(prev: str, pairs: list[tuple[str, str]]) -> str:
    """Resumo SEM LLM (usado quando o modelo falha ou demora): resumo anterior + últimos pedidos."""
    parts: list[str] = []
    if prev:
        parts.append("Resumo anterior: " + _clip(prev, 1500))
    asks = [_one_line(text, 300) for role, text in pairs if role == "human"][-6:]
    if asks:
        parts.append("Últimos pedidos do usuário:\n" + "\n".join(f"- {a}" for a in asks))
    answers = [_one_line(text, 500) for role, text in pairs if role == "ai"]
    if answers:
        parts.append("Última resposta do assistente: " + answers[-1])
    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# LLM, banco e estado do grafo
# ----------------------------------------------------------------------

async def _llm_summary(prev: str, transcript: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.graph.config import standard_llm

    parts: list[str] = []
    if prev:
        parts.append("RESUMO ANTERIOR DA CONVERSA:\n" + _clip(prev, 6000))
    parts.append("ÚLTIMAS MENSAGENS:\n" + transcript)
    messages = [SystemMessage(content=HANDOFF_PROMPT), HumanMessage(content="\n\n".join(parts))]
    response = await asyncio.wait_for(standard_llm.ainvoke(messages), timeout=_env_int("CHAT_HANDOFF_TIMEOUT", 120))
    return _THINK.sub("", _text_of(response.content)).strip()


async def build_handoff_text(old_title: str, old_summary: str, messages: list[Any], tasks: list[dict]) -> str:
    limit = max_handoff_chars()
    block = _clip(tasks_block(tasks), limit // 2)
    files = edited_files(messages)
    files_line = _clip("Arquivos editados nesta conversa: " + ", ".join(files), 300) if files else ""
    budget = max(400, limit - len(block) - len(files_line) - 60)
    pairs = meaningful_messages(messages)
    prev = plain_summary(old_summary)
    body = ""
    if pairs or prev:
        try:
            body = await _llm_summary(prev, build_transcript(pairs))
        except Exception as exc:
            _log(f"resumo pelo modelo falhou ({type(exc).__name__}: {exc}); usando resumo simples")
    if not body:
        body = fallback_summary(prev, pairs)
    head = f"Chat anterior: «{old_title}»."
    return "\n\n".join(part for part in (head, _clip(body, budget), files_line, block) if part)


async def _chat_title(thread_id: str) -> str | None:
    from sqlalchemy import select

    from backend.database.config import async_session_env
    from backend.database.models import AiChatModel

    async with async_session_env() as db:
        result = await db.execute(select(AiChatModel.title).where(AiChatModel.thread_id == thread_id))
        return result.scalar_one_or_none()


async def _create_chat_row(title: str) -> tuple[int, str]:
    from backend.database.config import async_session_env
    from backend.database.models import AiChatModel

    new_thread = str(uuid.uuid4())
    async with async_session_env() as db:
        chat = AiChatModel(thread_id=new_thread, title=title)
        db.add(chat)
        await db.commit()
        await db.refresh(chat)
        return chat.id, new_thread


async def _delete_chat_row(chat_id: int) -> None:
    from sqlalchemy import delete

    from backend.database.config import async_session_env
    from backend.database.models import AiChatModel

    async with async_session_env() as db:
        await db.execute(delete(AiChatModel).where(AiChatModel.id == chat_id))
        await db.commit()


async def _load_tasks(thread_id: str) -> list[dict]:
    from sqlalchemy import select

    from backend.database.config import async_session_env
    from backend.database.models import TaskModel

    async with async_session_env() as db:
        result = await db.execute(select(TaskModel).where(TaskModel.thread_id == thread_id).order_by(TaskModel.id))
        rows = result.scalars().all()
        tasks: list[dict] = []
        for t in rows:
            uploads = sorted(
                {
                    str(step.get("source"))
                    for step in (t.steps or [])
                    if isinstance(step, dict) and step.get("op") in UPLOAD_OPS and step.get("source")
                }
            )
            tasks.append(
                {"id": t.id, "title": t.title or "", "status": t.status, "error": t.last_error or "", "uploads": uploads}
            )
        return tasks


async def _move_tasks(ids: list[int], from_thread: str, to_thread: str) -> int:
    """Move as tasks em aberto (e só elas) de um chat para o outro. Devolve quantas foram movidas."""
    if not ids:
        return 0
    from sqlalchemy import update

    from backend.database.config import async_session_env
    from backend.database.models import TaskModel

    async with async_session_env() as db:
        result = await db.execute(
            update(TaskModel)
            .where(
                TaskModel.id.in_(ids),
                TaskModel.thread_id == from_thread,
                TaskModel.status.in_(OPEN_STATUSES),
            )
            .values(thread_id=to_thread)
        )
        await db.commit()
    moved = getattr(result, "rowcount", None)
    return len(ids) if moved is None or moved < 0 else int(moved)


async def _copy_pin(old_thread: str, new_thread: str) -> bool:
    """Copia o projeto/fontes do RAG fixados (tabela chat_pins) para o chat novo. Falha não bloqueia a troca."""
    from sqlalchemy import text

    from backend.database.config import async_session_env

    try:
        async with async_session_env() as db:
            row = (
                await db.execute(
                    text("SELECT workspace_path, source_ids FROM chat_pins WHERE thread_id = :t"), {"t": old_thread}
                )
            ).first()
            if row is None:
                return False
            await db.execute(
                text(
                    "INSERT INTO chat_pins (thread_id, workspace_path, source_ids, updated_at) "
                    "VALUES (:t, :w, :s, :u) ON CONFLICT (thread_id) DO NOTHING"
                ),
                {"t": new_thread, "w": row[0], "s": row[1], "u": datetime.now(timezone.utc).isoformat()},
            )
            await db.commit()
        return True
    except Exception as exc:
        _log(f"não consegui copiar o projeto fixado para o chat novo ({type(exc).__name__}: {exc})")
        return False


async def _drop_pin(thread_id: str) -> None:
    from sqlalchemy import text

    from backend.database.config import async_session_env

    try:
        async with async_session_env() as db:
            await db.execute(text("DELETE FROM chat_pins WHERE thread_id = :t"), {"t": thread_id})
            await db.commit()
    except Exception:
        pass


def _copy_uploads_sync(workspace: str, old_thread: str, new_thread: str) -> int:
    """Copia os anexos do chat (<workspace>/.assistant_uploads/<thread>/) para o chat novo."""
    from backend.api.uploads import UPLOAD_DIR_NAME, sanitize_thread_id

    if not workspace:
        return 0
    base = Path(workspace) / UPLOAD_DIR_NAME
    src, dst = base / sanitize_thread_id(old_thread), base / sanitize_thread_id(new_thread)
    if not src.is_dir() or dst.exists():
        return 0
    shutil.copytree(src, dst)
    return sum(1 for p in dst.rglob("*") if p.is_file())


async def _copy_uploads(workspace: str, old_thread: str, new_thread: str) -> int:
    try:
        return await asyncio.to_thread(_copy_uploads_sync, workspace, old_thread, new_thread)
    except Exception as exc:
        _log(f"não consegui copiar os anexos para o chat novo ({type(exc).__name__}: {exc})")
        return 0


def _drop_uploads_sync(workspace: str, new_thread: str) -> None:
    from backend.api.uploads import UPLOAD_DIR_NAME, sanitize_thread_id

    if workspace:
        shutil.rmtree(Path(workspace) / UPLOAD_DIR_NAME / sanitize_thread_id(new_thread), ignore_errors=True)


async def _update_state(app_graph: Any, thread_id: str, values: dict) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await app_graph.aupdate_state(config, values)
    except Exception:
        await app_graph.aupdate_state(config, values, as_node="__start__")


def _notice_text(new_title: str, tokens: int, turns: int, moved: int) -> str:
    text = (
        f"⚠️ Esta conversa ficou longa demais (≈{max(1, tokens // 1000)}k tokens, {turns} mensagens) "
        f"e precisa continuar em um chat novo.\n\nAbra **{new_title}**: ele já começa com um resumo de tudo o que aconteceu aqui"
    )
    return text + (f" e com as {moved} task(s) em aberto." if moved else ".")


def _response(content: str, created_at: str | None, marker: dict, elapsed: float = 0.0) -> dict:
    return {
        "content": content,
        "name": None,
        "created_at": created_at,
        "elapsed_seconds": round(elapsed, 2),
        "rotated": True,
        "new_chat": {"id": marker.get("chat_id"), "thread_id": marker.get("thread_id"), "title": marker.get("title")},
    }


def _already_response(last_message: Any, marker: dict) -> dict:
    created = (getattr(last_message, "additional_kwargs", None) or {}).get("created_at")
    return _response(_text_of(getattr(last_message, "content", "")), created, marker)


async def _rotate(app_graph: Any, thread_id: str, workspace_path: str, values: dict, messages: list[Any],
                  tasks: list[dict], tokens: int, turns: int, started: float) -> dict:
    from langchain_core.messages import AIMessage

    workspace = workspace_path or values.get("workspace_path") or ""
    old_title = await _chat_title(thread_id)
    new_title = next_title(old_title)
    handoff = await build_handoff_text(old_title or "chat anterior", values.get("summary") or "", messages, tasks)
    open_ids = [t["id"] for t in tasks if t["status"] in OPEN_STATUSES]

    chat_id, new_thread = await _create_chat_row(new_title)
    moved = 0
    pinned = False
    copied = 0
    try:
        now = _now()
        visible = (
            f"📎 **Continuação do chat «{old_title or 'anterior'}»**\n\n"
            f"Este chat já começa com o resumo abaixo no contexto:\n\n{handoff}"
        )
        await _update_state(
            app_graph,
            new_thread,
            {
                "messages": [
                    AIMessage(content=visible, additional_kwargs={"created_at": now, "message_tag": "chat_handoff_summary"})
                ],
                "summary": join_handoff(handoff, ""),
                "workspace_path": workspace,
            },
        )
        moved = await _move_tasks(open_ids, thread_id, new_thread)
        pinned = await _copy_pin(thread_id, new_thread)
        copied = await _copy_uploads(workspace, thread_id, new_thread)
        marker = {"thread_id": new_thread, "chat_id": chat_id, "title": new_title}
        notice = _notice_text(new_title, tokens, turns, moved)
        await _update_state(
            app_graph,
            thread_id,
            {
                "messages": [
                    AIMessage(
                        content=notice,
                        additional_kwargs={"created_at": now, "message_tag": "chat_handoff_notice", HANDOFF_TAG: marker},
                    )
                ]
            },
        )
    except Exception:
        # desfaz: devolve as tasks, apaga o vínculo e o chat novo; o chat antigo segue funcionando
        for undo in (
            lambda: _move_tasks(open_ids, new_thread, thread_id) if moved else asyncio.sleep(0),
            lambda: _drop_pin(new_thread) if pinned else asyncio.sleep(0),
            lambda: asyncio.to_thread(_drop_uploads_sync, workspace, new_thread) if copied else asyncio.sleep(0),
            lambda: _delete_chat_row(chat_id),
        ):
            try:
                await undo()
            except Exception as exc:
                _log(f"falha ao desfazer a troca de chat ({type(exc).__name__}: {exc})")
        raise

    _log(f"chat {thread_id} cheio (≈{tokens // 1000}k tokens, {turns} msgs) -> novo chat «{new_title}» ({new_thread}); {moved} task(s) movida(s)")
    return _response(notice, now, marker, time.perf_counter() - started)


async def chat_size(app_graph: Any, thread_id: str) -> dict:
    """Tamanho do chat para a tela: tokens estimados, limite, se está cheio, tasks ativas e (se já foi trocado) o chat novo."""
    state = await app_graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = state.values or {}
    messages = list(values.get("messages") or [])
    tokens = chat_tokens(messages, values.get("summary") or "")
    turns = count_turns(messages)
    marker = find_handoff(messages)
    tasks = await _load_tasks(thread_id)
    return {
        "tokens": tokens,
        "turns": turns,
        "limit_tokens": max_tokens(),
        "limit_messages": max_messages(),
        "full": is_full(tokens, turns),
        "rotated_to": (
            {"id": marker.get("chat_id"), "thread_id": marker.get("thread_id"), "title": marker.get("title")}
            if marker
            else None
        ),
        "active_tasks": [{"id": t["id"], "title": t["title"], "status": t["status"]} for t in tasks if t["status"] in ACTIVE_STATUSES],
    }


async def release_active_tasks(thread_id: str) -> list[int]:
    """Marca como 'failed' as tasks do chat presas em 'queued'/'running' (ex.: o worker caiu), liberando a troca de chat."""
    from sqlalchemy import update

    from backend.database.config import async_session_env
    from backend.database.models import TaskModel

    ids = [t["id"] for t in await _load_tasks(thread_id) if t["status"] in ACTIVE_STATUSES]
    if not ids:
        return []
    async with async_session_env() as db:
        await db.execute(
            update(TaskModel)
            .where(TaskModel.id.in_(ids), TaskModel.thread_id == thread_id, TaskModel.status.in_(ACTIVE_STATUSES))
            .values(
                status="failed",
                last_error="Liberada manualmente (o worker parou ou a execução ficou presa). "
                "Se ela chegou a editar arquivos, confira o diff e use Reprovar para desfazer.",
            )
        )
        await db.commit()
    return ids


async def maybe_rotate_chat(app_graph: Any, thread_id: str, workspace_path: str = "", *, busy: bool = False,
                            force: bool = False) -> dict:
    """Decide e (se for o caso) executa a troca de chat. Nunca levanta: em erro, o chat segue como estava.

    status: 'not_needed' | 'waiting' (cheio, mas há execução/task ativa) | 'rotated' | 'already' | 'error'.
    Em 'rotated'/'already' vem 'response' (aviso + new_chat) para devolver ao front no lugar da resposta.
    """
    started = time.perf_counter()
    try:
        if not force and max_tokens() <= 0 and max_messages() <= 0:
            return {"status": "not_needed"}
        config = {"configurable": {"thread_id": thread_id}}
        state = await app_graph.aget_state(config)
        values = state.values or {}
        messages = list(values.get("messages") or [])
        if not messages:
            return {"status": "not_needed"}
        existing = find_handoff(messages)
        if existing:
            return {"status": "already", "response": _already_response(messages[-1], existing)}

        tokens = chat_tokens(messages, values.get("summary") or "")
        turns = count_turns(messages)
        if not force and not is_full(tokens, turns):
            return {"status": "not_needed"}

        tasks = await _load_tasks(thread_id)
        if busy or any(t["status"] in ACTIVE_STATUSES for t in tasks):
            _log(f"chat {thread_id} cheio (≈{tokens // 1000}k tokens), mas há task/execução ativa: troca adiada até terminar")
            return {"status": "waiting"}

        async with _get_lock():
            fresh = await app_graph.aget_state(config)
            fresh_messages = list((fresh.values or {}).get("messages") or [])
            again = find_handoff(fresh_messages)
            if again:
                return {"status": "already", "response": _already_response(fresh_messages[-1], again)}
            response = await _rotate(app_graph, thread_id, workspace_path, fresh.values or values, fresh_messages,
                                     tasks, tokens, turns, started)
        return {"status": "rotated", "response": response}
    except Exception as exc:
        _log(f"não foi possível trocar de chat ({type(exc).__name__}: {exc}); seguindo neste chat")
        return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
