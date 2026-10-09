"""Funções utilitárias puras usadas pelos nós do grafo (sem acesso a LLM/DB)."""

import ast
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import SystemMessage

from .config import WRITE_AND_GIT_TOOLS


# ----------------------------------------------------------------------
# Metadados de mensagens (horário / tempo de resposta)
# ----------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stamp_message(msg, started_at: float | None = None):
    """Grava created_at (e opcionalmente elapsed_seconds) na mensagem."""
    msg.additional_kwargs.setdefault("created_at", now_iso())
    if started_at is not None:
        msg.additional_kwargs["elapsed_seconds"] = round(
            time.perf_counter() - started_at, 2
        )
    return msg


# ----------------------------------------------------------------------
# Tool calls / parsing / sintaxe
# ----------------------------------------------------------------------

def _extract_gatherer_tool_trace(messages, start_idx: int) -> list[dict]:
    """
    Extrai somente o nome e os argumentos das tools utilizadas
    durante a execução atual do Context Gatherer.

    Não preserva:
    - conteúdo de ToolMessage;
    - pensamentos do modelo;
    - IDs das tool calls;
    - respostas completas das ferramentas.
    """
    trace = []

    for msg in messages[start_idx + 1 :]:
        if msg.type != "ai":
            continue

        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            continue

        for tool_call in tool_calls:
            trace.append(
                {
                    "name": tool_call.get("name"),
                    "args": tool_call.get("args", {}),
                }
            )

    return trace


WRITE_TOOL_NAMES = {
    "create_new_file",
    "edit_existing_file",
    "batch_edit_file",
    "append_to_file",
    "create_git_branch",
}

# Subconjunto de WRITE_TOOL_NAMES que de fato modifica conteúdo de arquivo
# (create_git_branch não altera nenhum arquivo).
FILE_WRITE_TOOL_NAMES = WRITE_TOOL_NAMES - {"create_git_branch"}


def _has_write_call(messages) -> bool:
    return any(
        call["name"] in WRITE_TOOL_NAMES
        for msg in messages
        if getattr(msg, "tool_calls", None)
        for call in msg.tool_calls
    )


GENERATE_TOOL_NAMES = {tool.name for tool in WRITE_AND_GIT_TOOLS}


def _parse_xml_tool_fallback(content: str) -> list[dict]:
    """
    Recupera tool calls que o Qwen escreveu em formato XML no conteúdo
    da resposta quando o Ollama não conseguiu convertê-las para
    response.tool_calls.
    """

    if not content or "<function=" not in content:
        return []

    recovered_calls = []

    function_matches = re.finditer(
        r"<function=([^>\s]+)>(.*?)</function>",
        content,
        re.DOTALL,
    )

    for function_match in function_matches:
        tool_name = function_match.group(1).strip()

        # Segurança: só aceita ferramentas realmente registradas
        # no Generate.
        if tool_name not in GENERATE_TOOL_NAMES:
            print(
                f"⚠️ [PARSER FALLBACK] Tool '{tool_name}' "
                "não está registrada no Generate. Ignorando."
            )
            continue

        function_body = function_match.group(2)

        args = {}

        parameter_matches = re.finditer(
            r"<parameter=([^>\s]+)>(.*?)</parameter>",
            function_body,
            re.DOTALL,
        )

        for parameter_match in parameter_matches:
            parameter_name = parameter_match.group(1).strip()
            parameter_value = parameter_match.group(2).strip()

            args[parameter_name] = parameter_value

        recovered_calls.append(
            {
                "name": tool_name,
                "args": args,
                "id": f"fallback-{uuid.uuid4().hex}",
                "type": "tool_call",
            }
        )

    return recovered_calls


def _extract_edited_python_files(messages) -> list[str]:
    """
    Extrai (sem duplicar, preservando a ordem) os caminhos dos arquivos
    .py tocados por tool calls de escrita nas mensagens informadas.
    """
    edited_files: list[str] = []

    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            if call.get("name") not in FILE_WRITE_TOOL_NAMES:
                continue

            file_path = (call.get("args") or {}).get("file_path")

            if (
                isinstance(file_path, str)
                and file_path.endswith(".py")
                and file_path not in edited_files
            ):
                edited_files.append(file_path)

    return edited_files


def _check_python_syntax(file_paths: list[str], workspace: str | None) -> list[str]:
    """
    Faz ast.parse nos arquivos Python informados (resolvidos contra o
    workspace quando o caminho é relativo) e devolve a lista de erros.
    Lista vazia = tudo certo.
    """
    errors: list[str] = []

    for file_path in file_paths:
        path = Path(file_path)

        if not path.is_absolute() and workspace:
            path = Path(workspace) / path

        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append(
                f"{file_path}: linha {e.lineno}, coluna {e.offset} - {e.msg}"
            )
        except OSError as e:
            errors.append(f"{file_path}: não foi possível ler ({e})")

    return errors


def build_system_context(*parts: str | None) -> SystemMessage:
    """Junta múltiplas partes de contexto de sistema em uma única SystemMessage, separadas por um divisor."""
    valid_parts = [p.strip() for p in parts if p and p.strip()]
    return SystemMessage(content="\n\n---\n\n".join(valid_parts))


# ----------------------------------------------------------------------
# Formatação de saída do Heavy
# ----------------------------------------------------------------------

def format_task_description(task: dict) -> str:
    """Monta a descrição em Markdown de uma tarefa gerada pelo Heavy."""
    sections = [
        ("Objetivo", task.get("objective", "")),
        ("Localização Alvo", task.get("target", "")),
        ("Lógica da Alteração (Instruções Detalhadas)", task.get("logic", "")),
        ("Restrições do Usuário", task.get("constraints", "")),
    ]
    return "\n\n".join(
        f"**{label}:**\n{str(value).strip()}"
        for label, value in sections
        if value and str(value).strip()
    )


def build_security_report(findings: list[dict]) -> str:
    report = "\n\n## 🛡️ Achados de Segurança\n\n"
    for finding in findings:
        cat = finding.get("category", "Desconhecido")
        risk = str(finding.get("risk", "Desconhecido")).upper()
        file_path = finding.get("file", "Desconhecido")
        evidence = finding.get("evidence", "")
        tech = finding.get("technical_analysis", "")

        # cerca maior que qualquer ``` dentro da evidência
        fence = "`" * max(3, max((len(m) for m in re.findall(r"`+", evidence)), default=0) + 1)

        report += f"### 🔴 {cat} ({risk})\n"
        report += f"**Arquivo:** `{file_path}`\n"
        report += f"**Evidência (Código):**\n{fence}text\n{evidence}\n{fence}\n"
        report += f"**Análise Técnica:** {tech}\n\n"
    return report
