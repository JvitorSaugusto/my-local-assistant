"""Nó do modo Auditoria (@audit): determinístico, sem LLM. Toda a lógica pura está em audit_core.py."""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from backend.database.config import async_session_env
from backend.database.models import TaskModel

from backend.api.live_thoughts import live_progress
from backend.handoff.artifacts import record_artifact

from . import audit_core as ac
from .audit_pdf import build_audit_pdf
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


def _make_progress_cb(thread_id: str):
    stages: dict[str, str] = {}
    order: list[str] = []

    def cb(stage: str, detail: str) -> None:
        if stage not in stages:
            order.append(stage)
        stages[stage] = detail
        lines = []
        for idx, name in enumerate(order):
            marker = "⏳" if idx == len(order) - 1 else "✓"
            lines.append(f"{marker} {name}: {stages[name]}")
        live_progress(thread_id, f"Auditoria: {stage}", "\n".join(lines))

    return cb


def _scope_label(command: dict) -> str:
    if command.get("paths"):
        return ", ".join(command["paths"][:5]) + ("..." if len(command["paths"]) > 5 else "")
    if command.get("incremental"):
        base = command.get("base")
        return f"Alterações (diff base={base})" if base else "Alterações (git diff)"
    return "Projeto completo"


async def _generate_and_register_pdf(workspace: str, thread_id: str, result: dict, scope: str, progress_cb=None) -> str | None:
    if progress_cb:
        progress_cb("Relatório PDF", "gerando arquivo completo em PDF...")
    try:
        pdf_path = await asyncio.to_thread(build_audit_pdf, workspace, result, scope)
        await record_artifact(thread_id, pdf_path.name, "pdf", pdf_path.name, pdf_path.stat().st_size)
        if progress_cb:
            progress_cb("Relatório PDF", f"pronto ({pdf_path.name})")
        return pdf_path.name
    except Exception:  # noqa: BLE001
        return None


async def _run_audit_flow(workspace: str, thread_id: str, command: dict, skip_install_prompt: bool = False, prefix: str = "") -> dict:
    paths, errors = ac.expand_paths(workspace, command["paths"]) if command.get("paths") else (None, [])
    if command.get("paths") and not paths:
        return _reply("Nenhum arquivo .py/.js encontrado nos caminhos informados:\n" + "\n".join(f"- {e}" for e in errors))

    selected_tools = tuple(command["tools"]) if command.get("tools") else ac.DEFAULT_AUDIT_TOOLS
    if not skip_install_prompt:
        target_files = paths if paths is not None else await asyncio.to_thread(ac.project_code_files, workspace)
        has_py = any(f.endswith(".py") for f in target_files)
        missing = ac.missing_tools(selected_tools) if has_py else []
        if missing:
            await asyncio.to_thread(
                ac.save_pending_install,
                workspace,
                thread_id,
                {"command": command, "missing": missing},
            )
            pkgs = " ".join(missing)
            missing_fmt = ", ".join(f"`{m}`" for m in missing)
            return _reply(
                f"⚠️ **Ferramentas de auditoria ausentes no ambiente do assistente:** {missing_fmt}\n\n"
                f"Quer que eu instale agora com `pip install {pkgs}` e já rode a auditoria completa?\n\n"
                "- Responda **`sim`** (ou `@audit instalar`) para instalar e auditar.\n"
                "- Responda **`não`** (ou `@audit continuar`) para auditar agora usando apenas as ferramentas disponíveis."
            )

    progress_cb = _make_progress_cb(thread_id)
    kwargs = {"tools": selected_tools}
    result = await asyncio.to_thread(
        ac.run_audit,
        workspace,
        paths,
        bool(command.get("incremental")),
        command.get("base"),
        min_confidence=command.get("min") or "low",
        progress_cb=progress_cb,
        **kwargs,
    )
    scope = _scope_label(command)
    pdf_name = await _generate_and_register_pdf(workspace, thread_id, result, scope, progress_cb=progress_cb)
    result["scope_label"] = scope
    if pdf_name:
        result["pdf_filename"] = pdf_name
    await asyncio.to_thread(ac.save_last, workspace, thread_id, result)

    text = ac.format_report(result)
    if pdf_name:
        text += f"\n\n📄 **Relatório completo em PDF (salvo em Artefatos):** [{pdf_name}](/api/handoff/packs/{pdf_name})"
    if errors:
        text += "\n\nIgnorados: " + "; ".join(errors)
    if prefix:
        text = f"{prefix}\n\n{text}"
    return _reply(text)


async def audit_node(state: State, config: RunnableConfig):
    thread_id = str((config.get("configurable") or {}).get("thread_id", "thread_ausente"))
    workspace = str(state.get("workspace_path") or "").strip()
    command = ac.parse_command(_text_of(state["messages"][-1]), state.get("messages")) or {
        "cmd": "run", "incremental": False, "base": None, "min": "low", "tools": None, "paths": [],
    }

    if command["cmd"] == "help":
        return _reply(ac.AUDIT_HELP)
    if not workspace:
        return _reply("Nenhum diretório de trabalho foi definido para esta conversa. Fixe o projeto e tente de novo.")

    try:
        if command["cmd"] == "run":
            return await _run_audit_flow(workspace, thread_id, command)

        if command["cmd"] == "continue":
            pending = await asyncio.to_thread(ac.load_pending_install, workspace, thread_id)
            await asyncio.to_thread(ac.clear_pending_install, workspace, thread_id)
            pending_cmd = (pending or {}).get("command") or {
                "cmd": "run", "incremental": False, "base": None, "min": "low", "tools": None, "paths": [],
            }
            return await _run_audit_flow(workspace, thread_id, pending_cmd, skip_install_prompt=True)

        if command["cmd"] == "install":
            pending = await asyncio.to_thread(ac.load_pending_install, workspace, thread_id)
            explicit = [a.strip().lower() for a in (command.get("args") or []) if a.strip().lower() in ac.INSTALLABLE_TOOLS]
            targets = explicit or list((pending or {}).get("missing") or []) or ac.missing_tools()
            if not targets:
                await asyncio.to_thread(ac.clear_pending_install, workspace, thread_id)
                if pending and pending.get("command"):
                    return await _run_audit_flow(
                        workspace, thread_id, pending["command"], skip_install_prompt=True,
                        prefix="✅ Todas as ferramentas de auditoria já estão instaladas.",
                    )
                return _reply("✅ Todas as ferramentas de auditoria (`ruff`, `vulture`, `radon`, `bandit`) já estão instaladas.")
            progress_cb = _make_progress_cb(thread_id)
            outcome = await asyncio.to_thread(ac.install_tools, targets, progress_cb=progress_cb)
            await asyncio.to_thread(ac.clear_pending_install, workspace, thread_id)
            notes = []
            if outcome["installed"]:
                notes.append("✅ **Instaladas com sucesso:** " + ", ".join(f"`{p}`" for p in outcome["installed"]))
            if outcome["already"]:
                notes.append("ℹ️ **Já instaladas:** " + ", ".join(f"`{p}`" for p in outcome["already"]))
            if outcome["failed"]:
                fail_lines = "; ".join(f"`{k}` ({v})" for k, v in outcome["failed"].items())
                notes.append(f"⚠️ **Falha ao instalar:** {fail_lines}")
            summary = "\n".join(notes) or "Nenhuma biblioteca precisou ser instalada."
            if pending and pending.get("command"):
                return await _run_audit_flow(workspace, thread_id, pending["command"], skip_install_prompt=True, prefix=summary)
            return _reply(summary + "\n\nAgora você pode rodar `@audit` normalmente.")

        if command["cmd"] == "pdf":
            last = await asyncio.to_thread(ac.load_last, workspace, thread_id)
            if not last:
                return _reply("Não há relatório de auditoria nesta conversa. Rode `@audit` primeiro.")
            scope = str(last.get("scope_label") or "Projeto completo")
            pdf_name = await _generate_and_register_pdf(workspace, thread_id, last, scope)
            if not pdf_name:
                return _reply("Não foi possível gerar o PDF do relatório de auditoria.")
            last["pdf_filename"] = pdf_name
            await asyncio.to_thread(ac.save_last, workspace, thread_id, last)
            return _reply(f"📄 **Relatório completo em PDF (salvo em Artefatos):** [{pdf_name}](/api/handoff/packs/{pdf_name})")

        if command["cmd"] == "fix":
            paths, errors = ac.expand_paths(workspace, command["paths"]) if command["paths"] else (None, [])
            if command["paths"] and not paths:
                return _reply("Nenhum arquivo .py/.js encontrado nos caminhos informados:\n" + "\n".join(f"- {e}" for e in errors))
            if command["incremental"]:
                changed = await asyncio.to_thread(ac.changed_files, workspace, command["base"])
                if changed is None:
                    return _reply("Este diretório não é um repositório git; informe os arquivos ou rode `@audit fix` sem `diff`.")
                paths = [f for f in changed if f.endswith(".py")] if paths is None else [f for f in paths if f in set(changed)]
            elif paths is None:
                last_saved = await asyncio.to_thread(ac.load_last, workspace, thread_id)
                spacing_files = sorted({f["file"] for f in (last_saved or {}).get("findings") or [] if f.get("tool") == "spacing"})
                if spacing_files:
                    paths = spacing_files
            result = await asyncio.to_thread(ac.fix_spacing, workspace, paths)
            fixed = result["fixed"]
            if not fixed:
                msg = f"Nenhum erro de espaçamento de linhas em branco encontrado em {result['checked']} arquivo(s) .py."
            else:
                total_lines = sum(item["inserted_lines"] for item in fixed)
                body = "\n".join(
                    f"- `{item['file']}` — {item['issues']} ajuste(s) (+{item['inserted_lines']} linha(s) em branco)"
                    for item in fixed
                )
                msg = f"## Auditoria — Linhas em branco corrigidas\n\n{body}\n\nTotal: {len(fixed)} arquivo(s), +{total_lines} linha(s) em branco."
                last_saved = await asyncio.to_thread(ac.load_last, workspace, thread_id)
                if last_saved and last_saved.get("findings"):
                    fixed_set = {item["file"] for item in fixed}
                    last_saved["findings"] = [
                        f for f in last_saved["findings"]
                        if not (f.get("tool") == "spacing" and f.get("file") in fixed_set)
                    ]
                    await asyncio.to_thread(ac.save_last, workspace, thread_id, last_saved)
            all_errors = errors + (result.get("errors") or [])
            if all_errors:
                msg += "\n\nAvisos:\n" + "\n".join(f"- {e}" for e in all_errors)
            return _reply(msg)

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
