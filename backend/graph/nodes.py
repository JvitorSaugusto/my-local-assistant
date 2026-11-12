import asyncio
import re
import subprocess
import time
import uuid
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, update

from backend.database.config import async_session_env
from backend.database.models import TaskModel

from .config import (
    CODER_NUM_CTX,
    GENERATE_NUM_CTX,
    MAX_VERIFY_RETRIES,
    REVIEW_FREE_TASKS,
    State,
    code_llm_with_tools,
    context_gatherer_llm_with_tools,
    generate_llm_with_tools,
    heavy_llm_structured,
    note_llm_draft_with_tools,
    note_llm_final,
    router_structured,
    standard_llm,
)
from .prompts import (
    CODE_NODE_PROMPT,
    CONTEXT_GATHERER_PROMPT,
    GENERATE_NODE_PROMPT,
    HEAVY_NODE_PROMPT,
    NOTE_NODE_PROMPT,
    PROMPT_ENHANCER_NODE_PROMPT,
    ROUTER_NODE_PROMPT,
    STANDARD_NODE_PROMPT,
)
from .task_journal import begin_journal, journal_end, journal_rollback, syntax_problems_for_paths
from .task_commit import capture_originals, commit_task
from .ops_core import detect_ops_intent
from .node_helpers import (
    _check_python_syntax,
    _extract_edited_python_files,
    _extract_gatherer_tool_trace,
    _extract_written_files,
    _has_write_call,
    _messages_of_current_task,
    _parse_xml_tool_fallback,
    build_security_report,
    build_system_context,
    detect_project_stack,
    extract_repo_map_output,
    format_task_description,
    ground_dossier,
    mentions_internal_pipeline,
    needs_task_split,
    now_iso,
    number_generated_tasks,
    pick_map_dir,
    render_project_tree,
    starts_with_echo,
    validate_generated_tasks,
    wants_project_map,
    wants_tasks,
    stamp_message,
)
from .executor import execute_task, missing_listed_files, run_checks, workspace_summary
from .context_builder import build_task_dossier, estimate_tokens, format_report
from .grounding import auto_check_documents
from .rag_bridge import rag_context
from .answer_guard import build_answer_corpus, detect_repetition, finalize_answer, wants_raw_output
from .checklist import gatherer_coverage_part
from .heavy_rules import HEAVY_OUTPUT_RULES
from .snippet_validator import validate_snippets
from .supported_formats import READ_SUPPORT_FACTS, asks_about_read_support
from .utils import ATTACHMENT_MARKER, detect_explicit_route, strip_leading_tags


ATTACHMENT_FALLBACK_ROUTE = "NOTES"


def router_node(state: State):
    if state.get("enhanced_prompt"):
        last_msg = state["enhanced_prompt"]
    else:
        raw_content = state["messages"][-1].content

        if isinstance(raw_content, list):
            last_msg = " ".join(
                str(item.get("text", ""))
                for item in raw_content
                if isinstance(item, dict) and "text" in item
            )
        else:
            last_msg = str(raw_content)

    ops_text = None if (state.get("enhanced_prompt") or state.get("active_generate_task")) else detect_ops_intent(last_msg, state["messages"])
    if ops_text is not None:
        if isinstance(state["messages"][-1].content, str) and ops_text != last_msg:
            state["messages"][-1].content = ops_text
        print("🔀 [ROUTER] Rota: 'OPS' (git/pacote pelo chat)")
        return {"actual_route": "OPS", "enhance_before_heavy": False}

    explicit_route = detect_explicit_route(last_msg)

    if explicit_route == "ENHANCER_HEAVY":
        cleaned_msg = strip_leading_tags(last_msg)

        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'ENHANCER → HEAVY'")

        return {
            "actual_route": "ENHANCER",
            "enhance_before_heavy": True,
        }

    if explicit_route == "HEAVY":
        cleaned_msg = strip_leading_tags(last_msg)

        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'HEAVY'")

        return {
            "actual_route": "HEAVY",
            "enhance_before_heavy": False,
        }

    if explicit_route == "ENHANCER":
        cleaned_msg = strip_leading_tags(last_msg)

        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'ENHANCER'")

        return {
            "actual_route": "ENHANCER",
            "enhance_before_heavy": False,
        }

    if state.get("active_generate_task"):
        print("🔀 [ROUTER] Rota de Execução em Background: 'GENERATE_EXECUTE'")
        return {
            "actual_route": "GENERATE_EXECUTE",
            "enhance_before_heavy": False,
        }

    if "@generate" in last_msg.lower():
        print("🔀 [ROUTER] Rota de Despacho: 'GENERATE_DISPATCH'")
        return {
            "actual_route": "GENERATE_DISPATCH",
            "enhance_before_heavy": False,
        }

    if len(last_msg) > 600:
        msg_for_router = (
            last_msg[:300] + "\n\n... [CONTEÚDO LONGO OCULTO] ...\n\n" + last_msg[-300:]
        )
    else:
        msg_for_router = last_msg

    recent_messages = state["messages"][-5:-1]

    history_str = ""
    for m in recent_messages:
        if m.type == "system":
            continue

        role = "Usuário" if m.type == "human" else "Assistente"
        text = m.content if m.content else "[Ação: Leitura de Arquivo/Pasta]"

        content_trunc = text[:250] + "... [cortado]" if len(text) > 250 else text
        history_str += f"{role}: {content_trunc}\n"

    decision = router_structured.invoke(
        [
            SystemMessage(content=ROUTER_NODE_PROMPT),
            HumanMessage(
                content=(
                    "<contexto_da_conversa_recente>\n"
                    f"{history_str}\n"
                    "</contexto_da_conversa_recente>\n\n"
                    "<mensagem_do_usuario>\n"
                    f"{msg_for_router}\n"
                    "</mensagem_do_usuario>\n\n"
                    "Com base no contexto acima, para qual rota esta NOVA mensagem deve ir?"
                )
            ),
        ]
    )

    route = decision.route

    print(f"🔀 [ROUTER] Rota escolhida pelo LLM: '{route}'")

    # Anexos só podem ser lidos por rotas com tools de leitura; NORMAL não tem.
    if route == "NORMAL" and ATTACHMENT_MARKER in last_msg and state.get("workspace_path"):
        route = ATTACHMENT_FALLBACK_ROUTE
        print(f"🔀 [ROUTER] Mensagem com anexos: rota ajustada para '{route}'")

    return {
        "actual_route": route,
        "enhance_before_heavy": False,
    }


def enhancer_node(state: State):
    persona = SystemMessage(content=PROMPT_ENHANCER_NODE_PROMPT)

    last_message = state["messages"][-1]
    context = [persona, last_message]

    response = standard_llm.invoke(context)
    response.name = "GPT-OSS (20B) ENHANCER"
    response.additional_kwargs["message_tag"] = "internal_thought_enhancer"
    stamp_message(response)

    print("GPT-OSS (20B) ENHANCER")

    return {
        "enhanced_prompt": response.content,
    }


def after_enhancer_route(state: State):
    if state.get("enhance_before_heavy"):
        return "context_gatherer_node"  # Redireciona pro Coletor
    return "router_node"


def standard_node_20b(state: State):
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]

    if state.get("enhanced_prompt"):
        recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))

    context = [
        build_system_context(
            STANDARD_NODE_PROMPT,
            f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}"
            if actual_summary
            else None,
        )
    ]

    context.extend(recent_messages)

    response = standard_llm.invoke(context)
    print("=== STANDARD ===")
    print("length:", len(response.content))
    print("metadata:", response.response_metadata)
    print("content:", repr(response.content[-500:]))
    response.name = "GPT-OSS (20B)"
    response.additional_kwargs["message_tag"] = "response_standard"
    stamp_message(response)

    return {"messages": [response], "enhanced_prompt": None}


def code_node(state: State):
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]

    workspace_path = state.get("workspace_path", "Diretório não informado")

    if state.get("enhanced_prompt"):
        recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))

    prompt_with_workspace = f"{CODE_NODE_PROMPT}\n\n[CONTEXTO DO AMBIENTE]\nO caminho raiz do workspace atual é: {workspace_path}"

    context = [
        build_system_context(
            prompt_with_workspace,
            f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}"
            if actual_summary
            else None,
        )
    ]

    context.extend(recent_messages)

    response = code_llm_with_tools.invoke(context)
    response.name = "GPT-OSS (20B) CODE"
    response.additional_kwargs["message_tag"] = "response_code"
    stamp_message(response)

    return {"messages": [response], "active_node": "code_node", "enhanced_prompt": None}


async def generate_dispatch_node(state: State, config: RunnableConfig):
    last_msg = state["messages"][-1].content.lower()
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id", "thread_ausente")

    match = re.search(r"@generate\s+(.*)", last_msg)
    target_ids = []
    if match:
        target_ids = [int(x) for x in re.findall(r"\d+", match.group(1))]

    dispatched_count = 0
    report_lines: list[str] = []

    async with async_session_env() as db:
        stmt = select(TaskModel).where(
            TaskModel.thread_id == thread_id, TaskModel.status == "pending"
        )

        if target_ids:
            stmt = stmt.where(TaskModel.id.in_(target_ids))

        result = await db.execute(stmt.order_by(TaskModel.id))
        tasks_to_run = result.scalars().all()

        if not tasks_to_run:
            return {
                "messages": [
                    AIMessage(
                        content="Nenhuma tarefa pendente foi encontrada no banco para executar."
                    )
                ],
                "active_node": "generate_dispatch_node",
            }

        workspace_path = state.get("workspace_path")

        if not workspace_path:
            return {
                "messages": [
                    AIMessage(
                        content="Nenhum diretório de trabalho foi definido para esta conversa."
                    )
                ],
                "active_node": "generate_dispatch_node",
            }

        # Tarefas são processadas em ordem de id: as microtasks costumam
        # depender das anteriores. Se uma tarefa determinística falhar, as
        # seguintes NÃO rodam (ficam 'pending') para não empilhar erro.
        blocked_by: int | None = None
        ran_inline = False

        for task in tasks_to_run:
            if blocked_by is not None:
                report_lines.append(
                    f"⏸️ #{task.id} {task.title} — não executada: a tarefa #{blocked_by} "
                    "falhou antes. Corrija/reinicie a #" f"{blocked_by} e execute de novo."
                )
                continue

            if task.steps:
                # Microtask com passos exatos: executa na hora, sem LLM.
                ran_inline = True
                task.status = "running"
                task.attempts = (task.attempts or 0) + 1
                task.last_error = None
                await db.commit()

                pre_state = capture_originals(workspace_path, task.steps)
                run = await execute_task(
                    {"steps": task.steps, "verify": task.verify or []},
                    workspace_path,
                    thread_id,
                )

                if run.ok:
                    applied = sum(1 for item in run.log if item["status"] == "ok")
                    skipped = sum(1 for item in run.log if item["status"] == "skipped")
                    task.status = "completed"
                    task.last_error = None
                    extra = f", {skipped} já estava(m) aplicado(s)" if skipped else ""
                    report_lines.append(
                        f"✅ #{task.id} {task.title} — {applied} passo(s) aplicado(s){extra}."
                    )
                    commit_note = await asyncio.to_thread(commit_task, workspace_path, task.id, task.title, pre_state)
                    if commit_note:
                        report_lines.append(commit_note)
                    absent = missing_listed_files(task.files, workspace_path)
                    if absent:
                        report_lines.append(
                            f"⚠️ #{task.id}: estes arquivos de 'files' NÃO existem no workspace "
                            f"(nenhum passo os cria): {', '.join(absent)}"
                        )
                else:
                    task.status = "failed"
                    task.last_error = (run.error or "Falha desconhecida.")[:4000]
                    blocked_by = task.id
                    first_line = (run.error or "").split("\n", 1)[0]
                    report_lines.append(f"❌ #{task.id} {task.title} — FALHOU. {first_line}")

                await db.commit()
                continue

            # Tarefa descrita em texto: continua indo para o agente (Celery).
            from tasks import run_generate_task

            task_dict = {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "files": task.files,
                "reason": task.reason,
                "priority": task.priority,
                "code_snippet": task.code_snippet,
                "verify": task.verify or [],
                "status": "queued",
                "repo_path": workspace_path,
            }

            # Grava 'queued' ANTES de enviar: se o worker terminar rápido, o status
            # final dele (completed/failed) não pode ser sobrescrito por este commit.
            task.status = "queued"
            task.attempts = (task.attempts or 0) + 1
            task.last_error = None
            await db.commit()

            try:
                run_generate_task.delay(thread_id, task_dict)
            except Exception as exc:
                task.status = "failed"
                task.last_error = f"Não foi possível enviar a tarefa ao Celery/Redis: {exc}"[:4000]
                blocked_by = task.id
                await db.commit()
                report_lines.append(
                    f"❌ #{task.id} {task.title} — FALHOU ao enviar para o Celery: {exc}"
                )
                continue

            dispatched_count += 1

    if dispatched_count:
        report_lines.append(
            f"📤 {dispatched_count} tarefa(s) enviada(s) para execução em background (Celery)."
        )

    if ran_inline:
        report_lines.append(workspace_summary(workspace_path))

    msg_retorno = "\n".join(report_lines)

    return {
        "messages": [
            AIMessage(
                content=msg_retorno,
                additional_kwargs={
                    "message_tag": "response_dispatch",
                    "created_at": now_iso(),
                },
            )
        ],
        "active_node": "generate_dispatch_node",
    }


async def _generate_node_impl(state: State):
    actual_summary = state.get("summary", "")

    generate_start_idx = state.get("generate_start_idx")

    if generate_start_idx is None:
        last_human_idx = 0

        for i in range(len(state["messages"]) - 1, -1, -1):
            if state["messages"][i].type == "human":
                last_human_idx = i
                break

        generate_start_idx = last_human_idx

    recent_messages = state["messages"][generate_start_idx:].copy()

    task = state.get("active_generate_task")

    workspace = state.get("workspace_path")
    branch_context = None

    if workspace:
        repo = Path(workspace).resolve()

        try:
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=10,
            )

            current_branch = branch_result.stdout.strip()

            if current_branch and current_branch not in {"main", "master"}:
                branch_context = (
                    "STATUS DA BRANCH DO WORKSPACE: "
                    f"a branch atual é '{current_branch}'. "
                    "Uma branch de trabalho já está ativa. NÃO chame "
                    "'create_git_branch' novamente nesta execução; prossiga "
                    "para a próxima etapa da tarefa."
                )

        except (OSError, subprocess.SubprocessError):
            pass

    if state.get("enhanced_prompt"):
        for i in range(len(recent_messages) - 1, -1, -1):
            if recent_messages[i].type == "human":
                recent_messages[i] = HumanMessage(content=state["enhanced_prompt"])
                break

    dossier_text, dossier_report = "", {}
    if task:
        dossier_text, dossier_report = await asyncio.to_thread(
            build_task_dossier, workspace, list(task.files or [])
        )
        rag_text = await rag_context(workspace, f"{task.title}\n{(task.description or '')[:600]}")
        if rag_text:
            dossier_report["rag_chars"] = len(rag_text)
            header = "" if dossier_text else "## DOSSIÊ DE CONTEXTO (montado pelo sistema)\n"
            dossier_text = (
                (dossier_text + "\n\n" if dossier_text else header)
                + "### Trechos relacionados do repositório (RAG)\n"
                + rag_text
            )

    context = [
        build_system_context(
            GENERATE_NODE_PROMPT,
            (f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}")
            if actual_summary
            else None,
            branch_context,
            (f"TAREFA DE IMPLEMENTAÇÃO:\n\n{task.model_dump_json(indent=2)}")
            if task
            else None,
            dossier_text or None,
        )
    ]

    context.extend(recent_messages)

    prompt_tokens = estimate_tokens("\n".join(str(getattr(m, "content", "")) for m in context))
    context_notice = None
    first_call = not any(getattr(m, "type", "") == "ai" for m in _messages_of_current_task(recent_messages))
    if task and first_call:
        begin_journal(workspace, task.id)
        context_notice = AIMessage(
            content=format_report(dossier_report, GENERATE_NUM_CTX, prompt_tokens),
            name="Qwen3-Coder (Generate)",
            additional_kwargs={"message_tag": "internal_context_report"},
        )
        stamp_message(context_notice)
        print(f"\n{context_notice.content}\n")
    elif prompt_tokens > 0.85 * GENERATE_NUM_CTX:
        print(
            f"⚠️ [GENERATE] Prompt estimado em ~{prompt_tokens} tokens, perto do num_ctx={GENERATE_NUM_CTX}: "
            "o Ollama pode cortar o início sem avisar."
        )

    response = await generate_llm_with_tools.ainvoke(context)

    response.name = "Qwen3-Coder (Generate)"
    response.additional_kwargs["message_tag"] = "internal_thought_generate"
    stamp_message(response)

    recovered_tool_calls = []

    if not response.tool_calls and response.content:
        recovered_tool_calls = _parse_xml_tool_fallback(str(response.content))

    if recovered_tool_calls:
        print(
            "\n⚠️ [PARSER FALLBACK] "
            "Ollama retornou uma chamada de ferramenta como texto."
        )

        print(
            "🔧 [PARSER FALLBACK] Ferramentas recuperadas:",
            [call["name"] for call in recovered_tool_calls],
        )

        response = AIMessage(
            content="",
            tool_calls=recovered_tool_calls,
            additional_kwargs={
                "message_tag": "internal_tool_fallback",
            },
            name="Qwen3-Coder (Generate)",
        )

    print("\n===== GENERATE =====")
    print("TOOL_CALLS:", response.tool_calls)

    if response.content:
        print("CONTENT:\n", response.content)

    print("====================\n")

    messages_to_return = ([context_notice] if context_notice else []) + [response]

    is_final_response = not bool(response.tool_calls)

    if task and is_final_response:
        all_messages_this_run = recent_messages + messages_to_return

        wrote_something = _has_write_call(all_messages_this_run)

        content_str = str(response.content).strip().upper() if response.content else ""

        reported_ambiguous = content_str.startswith("TAREFA AMBÍGUA")

        if not wrote_something and not reported_ambiguous:
            print("⚠️ [GENERATE] Tentativa de finalizar sem ação. Aplicando Nudge...")

            nudge = HumanMessage(
                name="hidden_task_prompt",
                content=(
                    "Sua última resposta não executou nenhuma ferramenta "
                    "de forma válida.\n\n"
                    "Se ainda precisar investigar ou modificar o projeto, "
                    "USE AS FERRAMENTAS DISPONÍVEIS por meio do mecanismo "
                    "de Tool Calling.\n\n"
                    "Quando o formato XML de chamada for utilizado pelo "
                    "sistema, mantenha CADA chamada em UMA ÚNICA LINHA, "
                    "sem quebras de linha dentro de <function> ou "
                    "<parameter>.\n\n"
                    "CORRETO:\n"
                    "<function=read_file_chunk><parameter=file_path>"
                    "core/views.py</parameter><parameter=offset>400"
                    "</parameter><parameter=length>50</parameter>"
                    "</function>\n\n"
                    "NÃO escreva explicações no lugar da execução da "
                    "ferramenta.\n\n"
                    "Se a tarefa não puder ser concluída com segurança, "
                    "responda começando EXATAMENTE com "
                    "'TAREFA AMBÍGUA:' e explique o motivo."
                )
            )

            response2 = await generate_llm_with_tools.ainvoke(
                context + [response, nudge]
            )

            response2.name = "Qwen3-Coder (Generate)"
            response2.additional_kwargs["message_tag"] = "internal_system_nudge"
            stamp_message(response2)

            if not response2.tool_calls and response2.content:
                recovered_tool_calls = _parse_xml_tool_fallback(str(response2.content))

                if recovered_tool_calls:
                    print("\n⚠️ [PARSER FALLBACK] Nudge também retornou XML.")

                    print(
                        "🔧 [PARSER FALLBACK] Ferramentas recuperadas:",
                        [call["name"] for call in recovered_tool_calls],
                    )

                    response2 = AIMessage(
                        content="",
                        tool_calls=recovered_tool_calls,
                        additional_kwargs={"message_tag": "internal_tool_fallback"},
                        name="Qwen3-Coder (Generate)",
                    )

            print("\n===== GENERATE (NUDGE) =====")
            print("TOOL_CALLS:", response2.tool_calls)

            if response2.content:
                print("CONTENT:\n", response2.content)

            print("============================\n")

            messages_to_return.extend([nudge, response2])

            is_final_response = not bool(response2.tool_calls)

            all_messages_this_run = recent_messages + messages_to_return

            wrote_something = _has_write_call(all_messages_this_run)

            content_str2 = (
                str(response2.content).strip().upper() if response2.content else ""
            )

            reported_ambiguous = content_str2.startswith("TAREFA AMBÍGUA")

        if is_final_response:
            final_status = "completed"
            last_error = None

            # Só a execução ATUAL conta (o grafo guarda a conversa inteira, com tarefas antigas).
            task_messages = _messages_of_current_task(all_messages_this_run)
            wrote_something = _has_write_call(task_messages)

            if not wrote_something:
                final_status = "failed"
                last_error = (
                    str(response_text_for_error(messages_to_return))
                    if reported_ambiguous
                    else "A IA terminou sem executar nenhuma alteração."
                )
                print("⚠️ [GENERATE] Nenhuma alteração feita. Tarefa marcada como falha.")

            problems: list[str] = []

            syntax_errors = _check_python_syntax(_extract_edited_python_files(task_messages), workspace)
            syntax_errors = syntax_errors + syntax_problems_for_paths(workspace, _extract_written_files(task_messages))
            if syntax_errors:
                problems.append(
                    "Erro de sintaxe após as edições:\n" + "\n".join(f"- {err}" for err in syntax_errors)
                )

            if wrote_something:
                if task.verify:
                    check_failures = await asyncio.to_thread(run_checks, task.verify, workspace or "")
                    if check_failures:
                        problems.append(
                            "Verificação final falhou:\n" + "\n".join(f"- {item}" for item in check_failures)
                        )

                # Documento novo (.md/.txt): confere, sem LLM, se os valores citados existem nas fontes.
                grounding_failures = await asyncio.to_thread(
                    auto_check_documents,
                    _extract_written_files(task_messages, {"write_markdown_file", "create_new_file"}),
                    list(task.files or []),
                    workspace or "",
                )
                if grounding_failures:
                    problems.append(
                        "Valores do documento sem respaldo nas fontes:\n"
                        + "\n".join(f"- {item}" for item in grounding_failures)
                    )

            if problems and final_status == "completed":
                problem_report = "\n\n".join(problems)
                print(f"❌ [GENERATE] Revisão automática encontrou problemas:\n{problem_report}")

                retries_used = sum(
                    1
                    for msg in task_messages
                    if (getattr(msg, "additional_kwargs", None) or {}).get("message_tag") == "internal_verify_retry"
                )

                if retries_used < MAX_VERIFY_RETRIES:
                    correction = HumanMessage(
                        name="hidden_task_prompt",
                        content=(
                            "A revisão automática do sistema encontrou problemas no seu resultado "
                            f"(tentativa de correção {retries_used + 1} de {MAX_VERIFY_RETRIES}):\n\n"
                            f"{problem_report}\n\n"
                            "Corrija usando as ferramentas: releia o código REAL, ajuste o arquivo e, em "
                            "documentos, remova ou troque por VERIFICAR qualquer valor que não esteja "
                            "literalmente no código. Não responda apenas com texto."
                        ),
                        additional_kwargs={"message_tag": "internal_verify_retry"},
                    )
                    retry_response = await generate_llm_with_tools.ainvoke(
                        context + messages_to_return + [correction]
                    )
                    retry_response.name = "Qwen3-Coder (Generate)"
                    retry_response.additional_kwargs["message_tag"] = "internal_verify_retry_response"
                    stamp_message(retry_response)

                    if not retry_response.tool_calls and retry_response.content:
                        recovered_retry_calls = _parse_xml_tool_fallback(str(retry_response.content))
                        if recovered_retry_calls:
                            retry_response = AIMessage(
                                content="",
                                tool_calls=recovered_retry_calls,
                                additional_kwargs={"message_tag": "internal_tool_fallback"},
                                name="Qwen3-Coder (Generate)",
                            )

                    messages_to_return.extend([correction, retry_response])

                    if retry_response.tool_calls:
                        # Continua: as tools rodam e este nó revisa de novo ao terminar.
                        return {
                            "messages": messages_to_return,
                            "active_node": "generate_node",
                            "enhanced_prompt": None,
                            "active_generate_task": task,
                        }

                final_status = "failed"
                last_error = problem_report
                messages_to_return.append(
                    AIMessage(
                        content=(
                            "❌ A tarefa FALHOU na revisão automática:\n"
                            f"{problem_report}\n"
                            "Revise (ex.: `git diff` / `git checkout -- <arquivo>`) e use 'Reiniciar' no painel de tarefas."
                        ),
                        name="Qwen3-Coder (Generate)",
                        additional_kwargs={"message_tag": "internal_verify_gate", "created_at": now_iso()},
                    )
                )

            if final_status == "failed":
                restored = journal_rollback(workspace, task.id)
                if restored:
                    last_error = (
                        (last_error or "")
                        + f"\n\nAs alterações desta execução foram DESFEITAS automaticamente ({len(restored)} arquivo(s)). "
                        "Use 'Ver alterações' para ver o que a IA tentou."
                    ).strip()
            journal_end(workspace)

            if final_status == "completed" and REVIEW_FREE_TASKS:
                final_status = "review"
                messages_to_return.append(
                    AIMessage(
                        content="🔎 Tarefa pronta para revisão: veja as alterações no painel de tarefas e clique em Aprovar ou Reprovar.",
                        name="Qwen3-Coder (Generate)",
                        additional_kwargs={"message_tag": "internal_review_gate", "created_at": now_iso()},
                    )
                )

            async with async_session_env() as db:
                stmt = (
                    update(TaskModel)
                    .where(TaskModel.id == task.id)
                    .values(status=final_status, last_error=last_error)
                )

                await db.execute(stmt)
                await db.commit()

    return {
        "messages": messages_to_return,
        "active_node": "generate_node",
        "enhanced_prompt": None,
        "active_generate_task": (None if is_final_response else task),
    }


def response_text_for_error(messages) -> str:
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "ai" and msg.content:
            return str(msg.content).strip()[:1500]
    return "A IA reportou que a tarefa é ambígua."


async def _mark_task_failed(task_id: int, error: str) -> None:
    try:
        async with async_session_env() as db:
            await db.execute(
                update(TaskModel)
                .where(TaskModel.id == task_id, TaskModel.status != "completed")
                .values(status="failed", last_error=error[:2000])
            )
            await db.commit()
    except Exception as db_error:  # nunca esconder o erro original
        print(f"[GENERATE] Falha ao marcar tarefa {task_id} como failed: {db_error}")


async def generate_node(state: State):
    """Executa a tarefa; se der erro no meio, ela fica 'failed' (com o erro) e pode ser reiniciada."""
    try:
        return await _generate_node_impl(state)
    except Exception as exc:
        task = state.get("active_generate_task")
        if task:
            journal_rollback(state.get("workspace_path"), task.id)
            journal_end(state.get("workspace_path"))
            await _mark_task_failed(task.id, f"Erro durante a execução: {exc}")
        raise


ATTACHMENT_QA_PROMPT = (
    "Você é um assistente que responde perguntas sobre arquivos anexados pelo usuário. "
    "Leia o arquivo com as ferramentas e responda DIRETAMENTE ao que foi perguntado, em "
    "português, com as suas próprias palavras. Nunca copie nem reproduza o conteúdo do "
    "arquivo, não reescreva o documento e não transforme a resposta em nota técnica."
)
_NOTE_REQUEST_WORDS = ("nota", "anotaç", "anotac", "documenta", "markdown", "guia")


def _last_human_text(state: State) -> str:
    for message in reversed(state["messages"]):
        if message.type == "human":
            return message.content if isinstance(message.content, str) else str(message.content)
    return ""


def _is_attachment_question(state: State) -> bool:
    """True se o usuário anexou arquivo e está PERGUNTANDO sobre ele (não pedindo uma nota)."""
    text = _last_human_text(state)
    if ATTACHMENT_MARKER not in text:
        return False
    question = text.split(ATTACHMENT_MARKER, 1)[0].lower()
    return not any(word in question for word in _NOTE_REQUEST_WORDS)


def note_draft_node(state: State) -> State:
    if _is_attachment_question(state):
        qa_instruction = HumanMessage(
            content=(
                "MODO: RESPONDER PERGUNTA SOBRE ARQUIVO ANEXO\n\n"
                "1) Leia o(s) arquivo(s) listado(s) em '[Arquivos anexados]' com "
                "`read_file_content` (ou `read_file_chunk` se for grande). Antes de cada "
                "chamada, escreva uma linha 'Raciocínio: [motivo]'.\n"
                "2) Depois de ler, responda DIRETAMENTE à pergunta do usuário, com as suas "
                "palavras. NÃO copie trechos longos, NÃO reproduza a estrutura do arquivo, "
                "NÃO gere nota técnica nem título com '# '.\n"
                "3) Se a pergunta for algo como 'do que se trata?', entregue um resumo curto "
                "(3 a 6 frases): assunto, objetivo e os pontos principais; no máximo uma "
                "lista curta. Se o usuário perguntou algo específico, responda só isso.\n"
                "4) Se o arquivo não tiver a informação pedida, diga isso claramente."
            )
        )
        qa_context = [SystemMessage(content=ATTACHMENT_QA_PROMPT)] + state["messages"][-6:] + [qa_instruction]
        qa_draft = note_llm_draft_with_tools.invoke(qa_context)
        qa_draft.name = "Qwen3 Notas Draft"
        qa_draft.additional_kwargs["message_tag"] = "internal_thought_draft"
        stamp_message(qa_draft)
        return {
            "messages": [qa_draft],
            "active_node": "note_draft_node",
            "enhanced_prompt": None,
        }

    persona = SystemMessage(content=NOTE_NODE_PROMPT)

    recent_messages = state["messages"][-6:]

    if state.get("enhanced_prompt"):
        recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))

    last_user_message = recent_messages[-1].content if recent_messages else ""

    is_update = (
        "##" in last_user_message
        or "# " in last_user_message
        or "atualiz" in last_user_message.lower()
        or "update" in last_user_message.lower()
    )
    mode = "ATUALIZAÇÃO DE NOTA" if is_update else "GERAÇÃO DE NOTA"

    instruction = HumanMessage(
        content=(
            f"MODO: {mode}\n\n"
            "Se a nota mencionar um projeto, diretório ou arquivo real, você DEVE "
            "chamar `list_directory_files` e/ou `read_file_content` antes de escrever "
            "qualquer conteúdo técnico sobre ele — mesmo que você acredite já saber "
            "a estrutura pelo histórico da conversa. Antes de cada chamada, escreva "
            "uma linha 'Raciocínio: [motivo]'. Nunca escreva nomes de arquivos, "
            "modelos ou tecnologias que não tenham sido confirmados por uma chamada "
            "de ferramenta ou pela mensagem do usuário.\n\n"
            "Transforme o conteúdo acima em uma nota técnica seguindo todas as "
            "regras do prompt do sistema.\n\nRetorne somente a nota final em Markdown."
        )
    )

    context = [persona] + recent_messages + [instruction]

    draft = note_llm_draft_with_tools.invoke(context)
    draft.name = "Qwen3 Notas Draft"
    draft.additional_kwargs["message_tag"] = "internal_thought_draft"
    stamp_message(draft)

    print("\n=== DRAFT NODE ===")
    print("Possui tool calls?", bool(draft.tool_calls))
    if draft.content:
        print("Tamanho do rascunho:", len(draft.content))

    return {
        "messages": [draft],
        "active_node": "note_draft_node",
        "enhanced_prompt": None,
    }


def note_refine_node(state: State) -> State:
    draft_msg = state["messages"][-1]
    draft_content = draft_msg.content

    print("\n=== REFINE NODE ===")

    # Pergunta sobre anexo: o rascunho já é a resposta. Reescrevê-lo como nota
    # técnica foi o que fazia o assistente repetir o arquivo em vez de responder.
    if _is_attachment_question(state) and draft_content and draft_content.strip():
        draft_msg.name = "Qwen3 Notas Final (30B)"
        draft_msg.additional_kwargs["message_tag"] = "response_note"
        stamp_message(draft_msg)
        return {"messages": [draft_msg]}

    persona = SystemMessage(content=NOTE_NODE_PROMPT)

    if not draft_content or not draft_content.strip():
        print("Aviso: Rascunho vazio chegou no Refine.")
        recent_messages = state["messages"][-6:]
        final_response = note_llm_final.invoke([persona] + recent_messages)
    else:
        refinement_prompt = f"""
        Aqui está um rascunho de nota (uso interno, não deve aparecer na sua resposta):

        <rascunho>
        {draft_content}
        </rascunho>

        Reescreva mantendo tudo que já está correto e adicionando profundidade
        onde fizer sentido (segundo exemplo, o "porquê" de decisões técnicas,
        diferenciação de conceitos). Não invente informações que não estejam
        no rascunho, no histórico da conversa ou no conteúdo lido pelas ferramentas.

        Responda somente com a nota final e reescrita, em Markdown, começando
        direto com '# '. Não inclua o rascunho nem comentários sobre o processo.
        """

        final_response = note_llm_final.invoke(
            [
                persona,
                HumanMessage(content=refinement_prompt),
            ]
        )

        if not final_response.content.strip():
            final_response = draft_msg

    final_response.name = "Qwen3 Notas Final (30B)"
    final_response.additional_kwargs["message_tag"] = "response_note"
    stamp_message(final_response)
    return {"messages": [final_response]}


def _previous_turns(messages: list, before_idx: int, max_messages: int = 6, max_chars: int = 1500) -> list:
    """Últimas mensagens de conversa (humano/IA, só texto) ANTES de before_idx.
    Serve para perguntas de acompanhamento não perderem o assunto."""
    picked = []
    for msg in messages[:before_idx]:
        if msg.type not in ("human", "ai"):
            continue
        if getattr(msg, "tool_calls", None):
            continue
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if kwargs.get("message_tag") in ("internal_thought_gatherer", "internal_task_instruction"):
            continue
        text = msg.content.strip() if isinstance(msg.content, str) else ""
        if not text:
            continue
        cls = HumanMessage if msg.type == "human" else AIMessage
        picked.append(cls(content=text[:max_chars]))
    return picked[-max_messages:]


def context_gatherer_node(state: State):
    actual_summary = state.get("summary", "")

    last_human_idx = 0

    for i in range(len(state["messages"]) - 1, -1, -1):
        if state["messages"][i].type == "human":
            last_human_idx = i
            break

    recent_messages = state["messages"][last_human_idx:].copy()

    if state.get("enhanced_prompt"):
        enhanced = HumanMessage(content=state["enhanced_prompt"])

        for index in range(len(recent_messages) - 1, -1, -1):
            if recent_messages[index].type == "human":
                recent_messages[index] = enhanced
                break

    workspace = state.get("workspace_path")
    stack = detect_project_stack(workspace)

    context = [
        build_system_context(
            CONTEXT_GATHERER_PROMPT,
            (f"RESUMO DA CONVERSA:\n{actual_summary}" if actual_summary else None),
            (
                "ESTRUTURA REAL DO WORKSPACE (verificada no disco):\n"
                f"{stack}\n"
                "Só existem as pastas listadas acima. NUNCA presuma pastas como "
                "`backend/`, `app/` ou `src/`: use apenas o que o mapa mostrar."
            )
            if stack
            else None,
            (
                "Ao usar 'list_directory_files' ou 'read_file_content', envie SEMPRE "
                "caminhos relativos à raiz do projeto (ex: 'tasks.py', 'backend/main.py'). "
                "O sistema já resolve isso automaticamente contra o workspace correto — "
                "não é necessário (e não deve) incluir o caminho completo do disco."
            )
            if workspace
            else None,
        )
    ]

    coverage = gatherer_coverage_part(_last_human_text(state))
    if coverage:
        context[0] = SystemMessage(content=str(context[0].content) + "\n\n" + coverage)

    context.extend(_previous_turns(state["messages"], last_human_idx))
    context.extend(recent_messages)

    prompt_chars = sum(len(str(getattr(m, "content", ""))) for m in context)
    est_tokens = prompt_chars // 3 + 1
    if est_tokens > CODER_NUM_CTX * 0.8:
        print(
            f"[⚠️ GATHERER] Prompt ≈ {est_tokens} tokens de {CODER_NUM_CTX}: o Ollama pode "
            "cortar o INÍCIO (as instruções). Aumente CODER_NUM_CTX ou reduza as leituras."
        )

    response = context_gatherer_llm_with_tools.invoke(context)

    ran_tools = any(m.type == "tool" for m in state["messages"][last_human_idx + 1 :])
    if workspace and not response.tool_calls and not ran_tools:
        print(
            "[GATHERER] ⚠️ O modelo respondeu sem ler nada do projeto (dossiê inventado). "
            "Forçando generate_repo_map('.')."
        )
        response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "generate_repo_map",
                    "args": {"dir_path": "."},
                    "id": f"auto-{uuid.uuid4().hex[:8]}",
                    "type": "tool_call",
                }
            ],
        )

    response.name = "Qwen3-Coder (Context Gatherer)"
    response.additional_kwargs["message_tag"] = "internal_thought_gatherer"

    print("\n===== CONTEXT GATHERER =====")
    print("TOOL_CALLS:", response.tool_calls)

    if response.content:
        print("CONTENT LENGTH:", len(response.content))
        print("CONTENT:")
        print(response.content)

    print("============================\n")

    if response.tool_calls:
        return {
            "messages": [response],
            "active_node": "context_gatherer_node",
            "enhanced_prompt": None,
        }

    gatherer_tool_trace = _extract_gatherer_tool_trace(
        state["messages"],
        last_human_idx,
    )

    repo_map_raw = extract_repo_map_output(state["messages"], last_human_idx, _last_human_text(state))

    dossier_text, ungrounded = ground_dossier(response.content or "", workspace)
    if ungrounded:
        print(f"[GATHERER] ⚠️ Arquivos citados que NÃO existem no projeto (removidos do dossiê): {ungrounded}")
        dossier_text += (
            "\n\nVERIFICAÇÃO AUTOMÁTICA: estes caminhos foram citados mas NÃO existem no projeto "
            "e foram descartados: " + ", ".join(f"`{p}`" for p in ungrounded) + "."
        )

    messages_to_remove = [
        RemoveMessage(id=msg.id)
        for msg in state["messages"][last_human_idx + 1 :]
        if getattr(msg, "id", None)
    ]

    dossier_text, bad_snippets = validate_snippets(dossier_text, workspace)
    if bad_snippets:
        print(f"[GATHERER] ⚠️ Trechos do dossiê que NÃO existem no arquivo real (removidos): {bad_snippets}")

    print("\n===== LIMPEZA DO GATHERER =====")
    print(f"[🧹] Mensagens internas removidas: {len(messages_to_remove)}")
    print(f"[🧰] Tool calls preservadas no trace: {len(gatherer_tool_trace)}")
    print(
        f"[📄] Dossiê salvo em heavy_context: {len(response.content or '')} caracteres"
    )
    print("===============================\n")

    return {
        "messages": messages_to_remove,
        "heavy_context": dossier_text,
        "repo_map_raw": repo_map_raw,
        "project_stack": stack,
        "gatherer_tool_trace": gatherer_tool_trace,
        "active_node": "context_gatherer_node",
        "enhanced_prompt": None,
    }


def _heavy_result_dict(result) -> dict:
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    if isinstance(result, dict):
        return result
    return {}


def _heavy_problems(data: dict, user_text: str, workspace: str | None, stack: str | None) -> list[str]:
    """Defeitos objetivos da resposta do Heavy (checados por código, não pelo modelo)."""
    problems: list[str] = []
    analysis = str(data.get("analysis") or "")
    if mentions_internal_pipeline(analysis) or starts_with_echo(analysis):
        problems.append(
            "O texto cita 'dossiê'/'coletor'/'tool calls' ou repete o pedido do usuário. "
            "Responda direto, começando pela resposta, citando arquivos e funções reais do projeto."
        )

    if wants_tasks(user_text):
        tasks = data.get("tasks") or []
        valid, discarded = validate_generated_tasks(tasks, workspace, stack)
        if not tasks:
            problems.append("O usuário pediu tasks, mas a lista `tasks` veio vazia. Gere as tasks.")
        problems.extend(discarded)
        if tasks and needs_task_split(user_text) and len(valid) < 4:
            problems.append(
                "Funcionalidade grande demais para poucas tasks: gere de 6 a 10 tasks pequenas, "
                "uma por responsabilidade (config, serializer, cada endpoint, rotas, proteção, teste), "
                "em ordem de execução, usando só arquivos e pastas que existem na estrutura real."
            )
    return problems


async def _review_heavy_result(result, context, user_text: str, workspace: str | None, stack: str | None):
    """Reprova a resposta com defeitos objetivos e pede UMA nova tentativa com o motivo."""
    data = _heavy_result_dict(result)
    problems = _heavy_problems(data, user_text, workspace, stack)
    if not problems:
        return result

    print("\n[HEAVY] ⚠️ Revisão automática reprovou a resposta:")
    for problem in problems:
        print(f"  - {problem}")

    feedback = HumanMessage(
        content=(
            "REVISÃO AUTOMÁTICA: a resposta anterior foi reprovada pelos motivos abaixo. "
            "Refaça a resposta COMPLETA (`analysis` e `tasks`) corrigindo cada ponto, "
            "sem mencionar esta revisão.\n"
            + "\n".join(f"- {problem}" for problem in problems)
            + f"\n\nPedido original do usuário: {user_text}"
        )
    )
    retry = await heavy_llm_structured.ainvoke([*context, feedback])
    retry_problems = _heavy_problems(_heavy_result_dict(retry), user_text, workspace, stack)
    print(f"[HEAVY] Segunda tentativa: {len(retry_problems)} problema(s) restante(s).")
    return retry if len(retry_problems) <= len(problems) else result


async def _retry_if_degenerate(result, context, user_text: str):
    """Se a resposta saiu em loop (itens repetidos), refaz UMA vez com limite explícito."""
    data = _heavy_result_dict(result)
    if not detect_repetition(str(data.get("analysis") or "")):
        return result
    print("[HEAVY] ⚠️ Resposta repetitiva (loop de geração). Refazendo uma vez.")
    feedback = HumanMessage(
        content=(
            "REVISÃO AUTOMÁTICA: a resposta anterior entrou em loop e repetiu itens. Refaça `analysis` curto, "
            "sem repetir nenhum item e com no máximo 40 itens por lista, citando só o que existe nos fatos verificados, "
            "sem mencionar esta revisão.\n\nPedido original do usuário: " + user_text
        )
    )
    return await heavy_llm_structured.ainvoke([*context, feedback])


async def heavy_analyzer_node(
    state: State,
    config: RunnableConfig,
):
    actual_summary = state.get("summary", "")
    dossier = state.get("heavy_context", "")
    gatherer_tool_trace = state.get("gatherer_tool_trace", [])
    repo_map_raw = state.get("repo_map_raw") or ""
    stack = state.get("project_stack") or ""
    workspace = state.get("workspace_path")

    configurable = config.get("configurable") or {}
    thread_id = configurable.get(
        "thread_id",
        "thread_ausente",
    )

    user_request = None

    for message in reversed(state["messages"]):
        if message.type == "human":
            user_request = message
            break

    user_text = (
        user_request.content if user_request is not None and isinstance(user_request.content, str) else ""
    )

    context = [
        build_system_context(
            HEAVY_NODE_PROMPT,
            f"RESUMO DA CONVERSA:\n{actual_summary}" if actual_summary else None,
            (
                "--- FATOS VERIFICADOS DO PROJETO (uso interno) ---\n"
                f"{stack or 'Stack não detectada.'}\n\n"
                + (f"ESTRUTURA REAL DE PASTAS E ARQUIVOS:\n{repo_map_raw}\n\n" if repo_map_raw else "")
                + "ARQUIVOS LIDOS E TRECHOS REAIS:\n"
                f"{dossier}\n"
                "---------------------------------------------------\n"
                "Esses fatos vêm do projeto real do usuário: use-os como fonte primária. "
                "NUNCA mencione 'dossiê', 'coletor', 'tool calls' ou 'contexto fornecido' na resposta: "
                "fale direto com o usuário, como quem leu o projeto pessoalmente. "
                "Só existem os arquivos e pastas listados acima; não cite nenhum outro caminho."
            )
            if (dossier and dossier.strip()) or repo_map_raw
            else None,
        )
    ]

    extra_rules = [HEAVY_OUTPUT_RULES]
    if asks_about_read_support(user_text):
        extra_rules.append(READ_SUPPORT_FACTS)
    context[0] = SystemMessage(content=str(context[0].content) + "\n\n" + "\n\n".join(extra_rules))

    if user_request:
        user_idx = next(
            (i for i in range(len(state["messages"]) - 1, -1, -1) if state["messages"][i] is user_request),
            len(state["messages"]),
        )
        context.extend(_previous_turns(state["messages"], user_idx))
        context.append(user_request)

    prompt_chars = sum(len(str(getattr(m, "content", ""))) for m in context)
    est_tokens = prompt_chars // 3 + 1
    print(f"\n[⏳ AGUARDE] Heavy (Qwen3-Coder) processando {len(context)} mensagens...")
    print(
        f"[📄 HEAVY] Dossiê: {len(dossier or '')} chars | mapa bruto: {len(repo_map_raw)} chars | "
        f"stack: {stack.splitlines()[0] if stack else 'n/d'}"
    )
    print(f"[📏 HEAVY] Prompt ≈ {est_tokens} tokens de {CODER_NUM_CTX} (num_ctx)")
    if est_tokens > CODER_NUM_CTX * 0.8:
        print(
            "[⚠️ HEAVY] Prompt perto do num_ctx: o Ollama corta o INÍCIO (as instruções). "
            "Aumente CODER_NUM_CTX no .env ou reduza o contexto."
        )

    start_time = time.time()

    result = await heavy_llm_structured.ainvoke(context)
    result = await _review_heavy_result(result, context, user_text, workspace, stack)
    result = await _retry_if_degenerate(result, context, user_text)

    elapsed_time = time.time() - start_time
    print(f"TEMPO DE RESPOSTA DO HEAVY: {elapsed_time:.2f} segundos")

    try:
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif hasattr(result, "dict"):
            data = result.dict()
        elif isinstance(result, dict):
            data = result
        else:
            data = {}

        final_analysis_content = data.get("analysis", "") or ""
        findings = data.get("security_findings", [])

        real_findings = [
            f for f in findings if f.get("exploitability_confirmed", False) is True
        ]

        if real_findings:
            final_analysis_content += build_security_report(real_findings)

        if not wants_raw_output(user_text):
            guarded = finalize_answer(
                final_analysis_content,
                build_answer_corpus(dossier, repo_map_raw, stack, state["messages"], gatherer_tool_trace),
                check_names=bool((dossier or "").strip()),
            )
            if guarded["invalid"]:
                print(f"[HEAVY] ⚠️ Nomes citados sem confirmação no código: {guarded['invalid']}")
            if guarded["degenerate"]:
                print("[HEAVY] ⚠️ Resposta ainda repetitiva depois da nova tentativa: descartada.")
                guarded["text"] = (
                    "Minha resposta saiu repetitiva e foi descartada. "
                    "Peça um item por vez ou diga qual arquivo quer ver."
                )
            final_analysis_content = guarded["text"]

        if not final_analysis_content.strip():
            final_analysis_content = (
                "✅ Análise concluída. Nenhuma tarefa gerada e nenhum resumo criado."
            )

        print("\n[DEBUG] === TEXTO FINAL QUE SERÁ ENVIADO AO FRONTEND ===")
        print(final_analysis_content)
        print("========================================================\n")

    except Exception as e:
        print(f"\n[ERRO FATAL NO FILTRO DE SEGURANÇA] {e}")
        final_analysis_content = (
            f"Erro interno ao processar o relatório de segurança: {e!s}"
        )
        data = {}

    tasks_data = data.get("tasks", []) or []

    if tasks_data:
        tasks_data, discarded = validate_generated_tasks(tasks_data, workspace, stack)
        if discarded:
            final_analysis_content += (
                "\n\n⚠️ Descartei estas tasks porque apontavam para algo que não existe no projeto "
                "ou estavam genéricas:\n" + "\n".join(f"- {item}" for item in discarded)
            )
        tasks_data = number_generated_tasks(tasks_data)

    if wants_project_map(user_text) and not tasks_data:
        tree_dir = pick_map_dir(workspace, gatherer_tool_trace, user_text)
        tree_text = render_project_tree(tree_dir) if tree_dir else ""
        if tree_text:
            final_analysis_content = (
                f"{final_analysis_content.strip()}\n\n**Mapa visual:**\n\n```text\n{tree_text}\n```"
            )

    if tasks_data:
        async with async_session_env() as db:
            try:
                for task in tasks_data:
                    description = format_task_description(task)

                    new_task = TaskModel(
                        thread_id=thread_id,
                        title=task.get("title", "Sem Título"),
                        description=description,
                        files=task.get("files", []),
                        reason=task.get("reason", ""),
                        priority=task.get("priority", "medium"),
                        code_snippet=(task.get("code_snippet") or "").strip() or None,
                        status="pending",
                    )

                    db.add(new_task)

                    print(f"\n--- TAREFA GERADA: {task.get('title')} ---")
                    print("files:", task.get("files"))
                    print("description:\n", description)
                    print("---")

                await db.commit()

            except Exception as e:
                await db.rollback()
                print(f"Erro ao salvar as tasks: {e}")
                raise

    print("\n===== HEAVY ANALYZER =====")
    print("TASKS GERADAS E SALVAS:", len(tasks_data))
    print("CONTENT LENGTH:", len(final_analysis_content))
    print("TOOL CALLS RECEBIDAS:", len(gatherer_tool_trace))
    print("DOSSIÊ RECEBIDO:", "SIM" if dossier else "NÃO")
    print("==========================\n")

    response = AIMessage(
        content=final_analysis_content,
        name="Qwen 3 Coder 30B",
        additional_kwargs={
            "message_tag": "response_heavy",
            "created_at": now_iso(),
        },
    )

    return {
        "messages": [response],
        "heavy_context": None,
        "repo_map_raw": None,
        "project_stack": None,
        "gatherer_tool_trace": [],
        "enhanced_prompt": None,
        "active_node": "heavy_analyzer_node",
    }


def route_decision(state: State):
    destiny = state.get("actual_route", "NORMAL")
    if destiny == "CODE":
        return "code_node"
    elif destiny == "HEAVY":
        workspace = state.get("workspace_path", "")

        if workspace is None:
            workspace = ""

        if workspace.strip():
            print("🔀 [EDGE] Rota HEAVY com tools. Indo para: context_gatherer_node")
            return "context_gatherer_node"

        else:
            print("🔀 [EDGE] Rota HEAVY sem tools. Indo para: heavy_analyzer_node")
            return "heavy_analyzer_node"

    elif destiny == "OPS":
        return "ops_node"
    elif destiny == "NOTES":
        return "note_draft_node"
    elif destiny == "ENHANCER":
        return "enhancer_node"
    elif destiny == "GENERATE_DISPATCH":
        return "generate_dispatch_node"  # Disparado pelo seu texto
    elif destiny == "GENERATE_EXECUTE":
        return "generate_node"  # Disparado pelo Celery
    return "standard_node_20b"


def check_context_limit(state: State):
    meaningful_count = 0

    for msg in state["messages"]:
        if msg.type == "tool":
            continue
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            continue

        meaningful_count += 1

    if meaningful_count > 10 and (meaningful_count - 1) % 10 == 0:
        print(
            f"\n[🔄 RESUMO] Limite de {meaningful_count} mensagens reais atingido. Gerando resumo..."
        )
        return "go_to_summarize"

    return "go_to_router"


def summarize_node(state: State):
    actual_summary = state.get("summary", "")
    all_messages = state["messages"]

    meaningful_messages = []

    for msg in all_messages:
        if msg.type == "tool":
            continue
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            continue

        meaningful_messages.append(msg)

    recent_messages = meaningful_messages[-10:]

    if actual_summary:
        prompt = f"Resumo atual da conversa: {actual_summary}\n\nLeia as novas mensagens acima e atualize o resumo para incluir esses novos assuntos. Mantenha em apenas um parágrafo conciso."
    else:
        prompt = "Resuma o assunto principal desta conversa acima em apenas um parágrafo conciso."

    order = HumanMessage(content=prompt)

    response = standard_llm.invoke(recent_messages + [order])

    return {"summary": response.content, "enhanced_prompt": None}


def return_tool_message(state: State):
    return state["active_node"]
