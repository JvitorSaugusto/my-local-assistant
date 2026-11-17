"""Nó do modo Auditoria (@audit): determinístico, sem LLM. Toda a lógica pura está em audit_core.py."""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from backend.database.config import async_session_env
from backend.database.models import TaskModel

from . import audit_core as ac
from .config import State
from .node_helpers import now_iso


def _text_of(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return " ".join(str(i.get("text", "")) for i in content if isinstance(i, dict))
    return str(content or "")


def _reply(text: str) -> dict:
    return {
        "messages": [AIMessage(content=text, additional_kwargs={"message_tag": "response_audit", "created_at": now_iso()})],
        "active_node": "audit_node",
    }


async def _create_tasks(thread_id: str, tasks: list[dict]) -> list[int]:
    async with async_session_env() as db:
        rows = [TaskModel(**task, thread_id=thread_id) for task in tasks]
        db.add_all(rows)
        await db.commit()
        for row in rows:
            await db.refresh(row)
        return [row.id for row in rows]


async def audit_node(state: State, config: RunnableConfig):
    thread_id = str((config.get("configurable") or {}).get("thread_id", "thread_ausente"))
    workspace = str(state.get("workspace_path") or "").strip()
    command = ac.parse_command(_text_of(state["messages"][-1])) or {"cmd": "run", "incremental": False, "base": None, "min": "low", "tools": None, "paths": []}

    if command["cmd"] == "help":
        return _reply(ac.AUDIT_HELP)
    if not workspace:
        return _reply("Nenhum diretório de trabalho foi definido para esta conversa. Fixe o projeto e tente de novo.")

    try:
        if command["cmd"] == "run":
            paths, errors = ac.expand_paths(workspace, command["paths"]) if command["paths"] else (None, [])
            if command["paths"] and not paths:
                return _reply("Nenhum arquivo .py/.js encontrado nos caminhos informados:\n" + "\n".join(f"- {e}" for e in errors))
            kwargs = {"tools": tuple(command["tools"])} if command["tools"] else {}
            result = await asyncio.to_thread(
                ac.run_audit, workspace, paths, command["incremental"], command["base"], min_confidence=command["min"], **kwargs
            )
            await asyncio.to_thread(ac.save_last, workspace, thread_id, result)
            text = ac.format_report(result)
            if errors:
                text += "\n\nIgnorados: " + "; ".join(errors)
            return _reply(text)

        last = await asyncio.to_thread(ac.load_last, workspace, thread_id)
        if not last or not last.get("findings"):
            return _reply("Não há relatório de auditoria nesta conversa. Rode `@audit` primeiro.")
        findings = last["findings"]

        if command["cmd"] == "tasks":
            chosen = ac.select_findings(findings, command.get("args") or [])
            if not chosen:
                return _reply("Nenhum achado corresponde aos números/ids informados.")
            ids = await _create_tasks(thread_id, ac.findings_to_tasks(chosen))
            return _reply(f"Criei {len(ids)} task(s) a partir de {len(chosen)} achado(s): "
                          + ", ".join(f"#{i}" for i in ids)
                          + ". Revise no painel e execute com `@generate` (elas são dinâmicas: o agente lê o arquivo e corrige).")

        if command["cmd"] == "fp":
            chosen = ac.select_findings(findings, command.get("args") or [])
            if not command.get("args") or not chosen:
                return _reply("Informe o número ou o id do achado: `@audit falso 4 motivo`.")
            await asyncio.to_thread(ac.mark_false_positive, workspace, chosen[0], command.get("reason") or "")
            last["findings"] = [f for f in findings if f["id"] != chosen[0]["id"]]
            await asyncio.to_thread(ac.save_last, workspace, thread_id, last)
            return _reply(f"Registrado como falso positivo: `{chosen[0]['file']}:{chosen[0]['line']}` ({chosen[0]['rule']}). Não aparece mais nas próximas auditorias.")

        if command["cmd"] == "unfp":
            args = command.get("args") or []
            if not args:
                return _reply("Informe o id: `@audit desfazer <id>`.")
            done = await asyncio.to_thread(ac.unmark_false_positive, workspace, args[0])
            return _reply("Removido do registro de falsos positivos." if done else "Esse id não está no registro.")
    except Exception as exc:  # a auditoria nunca derruba o chat
        return _reply(f"A auditoria falhou: {type(exc).__name__}: {exc}")
    return _reply(ac.AUDIT_HELP)
