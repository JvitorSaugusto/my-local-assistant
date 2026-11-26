"""Ferramentas de diagnóstico local para o modo Code: comandos seguros (allowlist) e teste HTTP em localhost."""

from __future__ import annotations

import io
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

_SHELL_META_RE = re.compile(r"[;&|`$><\r\n]")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_GIT_SUBCOMMANDS = {"status", "diff", "log", "branch", "rev-parse"}


def _validate_safe_command(command: str) -> tuple[list[str] | None, str | None]:
    raw = str(command or "").strip()
    if not raw:
        return None, "ERRO: comando vazio."
    if _SHELL_META_RE.search(raw):
        return None, "ERRO DE SEGURANÇA: operadores de shell (;, |, &, >, <, $, `) não são permitidos."
    try:
        tokens = shlex.split(raw, posix=(os.name != "nt"))
    except ValueError as exc:
        return None, f"ERRO ao interpretar comando: {exc}"
    if not tokens:
        return None, "ERRO: comando vazio."

    head = tokens[0].lower()
    sub = tokens[1].lower() if len(tokens) > 1 else ""
    sub2 = tokens[2].lower() if len(tokens) > 2 else ""

    if head == "git" and sub in _SAFE_GIT_SUBCOMMANDS:
        if sub == "branch" and any(flag in tokens[2:] for flag in ("-d", "-D", "-m", "-M", "--delete", "--move")):
            return None, "ERRO DE SEGURANÇA: apenas leitura de branches é permitida."
        return tokens, None

    if head == "npx" and sub == "tsc" and "--noEmit" in tokens[2:]:
        return tokens, None

    if head == "docker" and (sub == "ps" or (sub == "compose" and sub2 in {"ps", "config", "logs"})):
        if sub == "compose" and sub2 == "logs" and any(flag in tokens[3:] for flag in ("-f", "--follow")):
            return None, "ERRO DE SEGURANÇA: use `docker_monitor_control(action='start')` para acompanhar logs em tempo real (-f)."
        return tokens, None

    if head == "alembic" and sub in {"current", "heads", "history"}:
        return tokens, None

    if head in {"python", "python3", "py"} and sub == "manage.py" and sub2 in {"check", "showmigrations"}:
        return [sys.executable, *tokens[1:]], None

    if head == "ruff" and sub == "check":
        return tokens, None

    return None, (
        "ERRO DE SEGURANÇA: comando fora da allowlist. Permitidos: "
        "`git status/diff/log/branch`, `npx tsc --noEmit`, `docker ps`, `docker compose ps`, "
        "`alembic current/heads`, `python manage.py check/showmigrations`, `ruff check`."
    )


@tool
def run_safe_command(
    command: str,
    cwd_rel: str = "",
    workspace_path: Annotated[str, InjectedState("workspace_path")] = "",
) -> str:
    """Executa um comando seguro de diagnóstico somente-leitura no workspace (allowlist fixa, sem shell).

    Comandos permitidos: `git status`, `git diff`, `git log -n 10`, `git branch`,
    `npx tsc --noEmit`, `docker ps`, `docker compose ps`, `alembic current`,
    `python manage.py check`, `python manage.py showmigrations`, `ruff check`.

    Args:
        command: comando a executar.
        cwd_rel: subpasta relativa opcional dentro do workspace (ex.: 'dashboard').
    """
    tokens, error = _validate_safe_command(command)
    if error or not tokens:
        return error or "ERRO: comando inválido."

    if not workspace_path or not str(workspace_path).strip():
        return "ERRO: nenhum diretório de trabalho (workspace) está definido nesta conversa."

    root = Path(str(workspace_path)).resolve()
    target_cwd = (root / cwd_rel.strip()).resolve() if cwd_rel.strip() else root
    try:
        target_cwd.relative_to(root)
    except ValueError:
        return "ERRO DE SEGURANÇA: subpasta fora do workspace."
    if not target_cwd.is_dir():
        return f"ERRO: pasta '{cwd_rel}' não encontrada no workspace."

    try:
        done = subprocess.run(
            tokens,
            cwd=str(target_cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return f"ERRO: comando '{command}' passou de 30s e foi interrompido."
    except OSError as exc:
        return f"ERRO ao executar '{tokens[0]}': {exc}"

    out = (done.stdout or "").strip()
    err = (done.stderr or "").strip()
    combined = "\n".join(part for part in (out, err) if part) or "(sem saída)"
    if len(combined) > 6000:
        combined = combined[:6000].rstrip() + "\n[... saída cortada ...]"
    return f"exit_code={done.returncode}\n{combined}"


@tool
def local_http_check(
    url: str,
    method: str = "GET",
    body: str = "",
) -> str:
    """Faz uma requisição HTTP de teste EXCLUSIVAMENTE para localhost / 127.0.0.1 (ex.: testar API FastAPI/Django local).

    Args:
        url: URL local completa (ex.: 'http://127.0.0.1:8000/api/health').
        method: método HTTP ('GET', 'POST', 'HEAD', 'OPTIONS').
        body: corpo JSON opcional para POST.
    """
    raw_url = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(raw_url)
    except ValueError:
        return "ERRO: URL inválida."

    if parts.scheme not in ("http", "https"):
        return "ERRO: apenas http:// ou https:// são permitidos."
    host = (parts.hostname or "").lower()
    if host not in _LOCAL_HOSTS:
        return "ERRO DE SEGURANÇA: local_http_check aceita apenas localhost, 127.0.0.1 ou ::1."

    verb = str(method or "GET").strip().upper()
    if verb not in {"GET", "POST", "HEAD", "OPTIONS"}:
        return f"ERRO: método '{verb}' não permitido (use GET, POST, HEAD ou OPTIONS)."

    data = body.encode("utf-8") if body and verb == "POST" else None
    headers = {"User-Agent": "AssistenteLocal-Check/1.0"}
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(raw_url, data=data, headers=headers, method=verb)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            text = resp.read(8000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        text = exc.read(8000).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"ERRO ao conectar em {raw_url}: {exc}"

    if len(text) > 4000:
        text = text[:4000].rstrip() + "\n[... resposta cortada ...]"
    return f"HTTP {status} ({ctype or 'sem content-type'})\n\n{text or '(corpo vazio)'}"


def _parse_auth_headers(auth_header: str = "") -> dict[str, str]:
    """Aceita 'Header: valor', 'Bearer <token>' ou apenas '<token>' (vira Authorization: Bearer)."""
    raw = str(auth_header or "").strip()
    if not raw or "\r" in raw or "\n" in raw:
        return {}
    if ":" in raw:
        name, value = raw.split(":", 1)
        name, value = name.strip(), value.strip()
        if name and value:
            return {name: value}
        return {}
    if raw.lower().startswith("bearer "):
        return {"Authorization": raw}
    return {"Authorization": f"Bearer {raw}"}


def _probe_single_url(url: str, timeout: int = 8, extra_headers: dict[str, str] | None = None) -> dict:
    headers = {"User-Agent": "AssistenteLocal-RouteTest/1.0", **(extra_headers or {})}
    req = urllib.request.Request(url, headers=headers, method="GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            body = resp.read(1200).decode("utf-8", errors="replace").strip()
            return {"ok": 200 <= resp.status < 400, "status": resp.status, "ms": elapsed_ms, "detail": body[:300]}
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        body = exc.read(1200).decode("utf-8", errors="replace").strip()
        return {"ok": False, "status": exc.code, "ms": elapsed_ms, "detail": body[:400] or exc.reason}
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return {"ok": False, "status": 0, "ms": elapsed_ms, "detail": str(exc)[:300]}


def run_local_route_suite(base_url: str, routes: str = "", timeout: int = 8, auth_header: str = "") -> dict:
    """Descobre rotas GET seguras via /openapi.json (ou usa a lista informada) e testa cada uma em localhost."""
    import json

    raw_base = str(base_url or "").strip().rstrip("/")
    try:
        parts = urllib.parse.urlsplit(raw_base)
    except ValueError:
        return {"error": "URL base inválida."}
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in _LOCAL_HOSTS:
        return {"error": "ERRO DE SEGURANÇA: apenas localhost, 127.0.0.1 ou ::1 são permitidos."}

    extra_headers = _parse_auth_headers(auth_header)
    paths: list[str] = []
    discovered_via = "manual"
    if str(routes or "").strip():
        for token in re.split(r"[\n,]+", routes):
            p = token.strip()
            if p:
                paths.append(p if p.startswith("/") else "/" + p)
    else:
        try:
            req = urllib.request.Request(
                f"{raw_base}/openapi.json",
                headers={"User-Agent": "AssistenteLocal-RouteTest/1.0", **extra_headers},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                spec = json.loads(resp.read(500_000).decode("utf-8", errors="replace"))
            for path, methods in (spec.get("paths") or {}).items():
                if "{" in path or "}" in path:
                    continue
                if isinstance(methods, dict) and "get" in {k.lower() for k in methods}:
                    paths.append(path)
            if paths:
                discovered_via = "openapi.json"
        except Exception:
            pass
        if not paths:
            paths = ["/", "/health", "/api/health"]
            discovered_via = "fallback"

    paths = list(dict.fromkeys(paths))[:40]
    passed: list[dict] = []
    failed: list[dict] = []
    for path in paths:
        res = _probe_single_url(f"{raw_base}{path}", timeout=timeout, extra_headers=extra_headers)
        entry = {"path": path, **res}
        if res["ok"]:
            passed.append(entry)
        else:
            failed.append(entry)

    lines = [
        f"Teste de rotas em `{raw_base}` (origem: {discovered_via}) — **{len(passed)} passou**, **{len(failed)} falhou** (total: {len(paths)}):",
    ]
    if failed:
        lines.append("\n**Falhas:**")
        for item in failed:
            lines.append(f"- `{item['path']}` -> HTTP {item['status']} ({item['ms']} ms): {item['detail'][:200]}")
    if passed:
        lines.append("\n**Passaram:**")
        for item in passed[:20]:
            lines.append(f"- `{item['path']}` -> HTTP {item['status']} ({item['ms']} ms)")

    return {
        "base_url": raw_base,
        "discovered_via": discovered_via,
        "total": len(paths),
        "passed": passed,
        "failed": failed,
        "markdown": "\n".join(lines),
    }


@tool
def test_local_routes(base_url: str, routes: str = "", auth_header: str = "") -> str:
    """Testa em lote as rotas GET de uma API local (localhost/127.0.0.1).

    Se `routes` ficar vazio, descobre automaticamente as rotas GET sem parâmetros via `/openapi.json` (FastAPI)
    ou testa `/`, `/health` e `/api/health`. Devolve o relatório de quais passaram e quais falharam.

    Args:
        base_url: URL base local (ex.: 'http://127.0.0.1:8000').
        routes: lista opcional de rotas separadas por vírgula ou quebra de linha (ex.: '/api/health, /api/users').
        auth_header: opcional, token Bearer ou header completo (ex.: 'Authorization: Bearer ...' ou 'Cookie: ...').
    """
    res = run_local_route_suite(base_url, routes, auth_header=auth_header)
    if res.get("error"):
        return str(res["error"])
    return str(res["markdown"])


@tool
async def docker_monitor_control(
    action: str = "status",
    workspace_path: Annotated[str, InjectedState("workspace_path")] = "",
    thread_id: Annotated[str, InjectedState("thread_id")] = "",
) -> str:
    """Controla o monitor proativo de Docker Compose em background para o projeto ativo.

    Args:
        action: 'status' (ver estado e tempo do último build), 'start' (começar a escutar logs e avisar erros no chat),
                'stop' (parar monitoramento) ou 'build' (rodar `docker compose up -d --build` e medir o tempo).
    """
    from backend.api.docker_monitor import monitor_manager

    if not workspace_path or not str(workspace_path).strip():
        return "ERRO: selecione um projeto na aba Projeto antes de usar o monitor Docker."
    act = str(action or "status").strip().lower()
    if act == "start":
        info = await monitor_manager.start(workspace_path, thread_id)
        return f"Monitor Docker ATIVO para `{info['project_name']}`. Erros nos logs serão reportados automaticamente neste chat."
    if act == "stop":
        res = await monitor_manager.stop(workspace_path)
        return "Monitor Docker parado." if res.get("stopped") else str(res.get("message") or "Nenhum monitor ativo.")
    if act == "build":
        res = await monitor_manager.run_build(workspace_path, thread_id)
        return str(res.get("message") or "Build iniciado em background.")
    status = monitor_manager.status_all(workspace_path).get("active")
    if not status:
        return "Monitor Docker está PARADO para este projeto. Use action='start' ou a aba Monitor para iniciar."
    build_info = (
        f"{status['last_build_seconds']} s ({'OK' if status['last_build_ok'] else 'FALHOU'})"
        if status.get("last_build_seconds") is not None
        else "nenhum build medido ainda"
    )
    return (
        f"Monitor Docker (`{status['project_name']}`): {'ATIVO' if status['running'] else 'PARADO'} | "
        f"Build em andamento: {'sim' if status['building'] else 'não'} | "
        f"Último build: {build_info} | Linhas lidas: {status['lines_seen']} | Erros detectados: {status['errors_detected']}."
    )


@tool
def extract_code_snippets(
    queries: str,
    subpath: str = "",
    include_full_class: bool = False,
    save_txt: str = "always",
    workspace_path: Annotated[str, InjectedState("workspace_path")] = "",
) -> str:
    """Localiza múltiplos termos, rotas, funções ou classes no projeto e extrai o escopo COMPLETO (função, método ou classe/View inteira) sem cortar código.

    Ideal quando o usuário pedir trechos que citam termos específicos (ex.: "Gestor, Administrador, auth/jwt, _sync_user_to_god"),
    colar uma lista de pontos para inspecionar, ou pedir a classe/View inteira em texto ou `.txt`.

    Args:
        queries: termos, nomes de funções, rotas ou classes separados por vírgula ou quebra de linha.
        subpath: pasta(s) ou arquivo(s) relativo(s) opcional(is), separados por vírgula se houver mais de um (ex.: 'god-backend/app/routers, god-backend/app/main.py').
        include_full_class: True quando o usuário pedir a classe/View inteira onde o termo aparece.
        save_txt: 'auto' (salva `.txt` se for grande ou tiver 3+ trechos), 'always' (sempre gera `.txt` clicável) ou 'never' (só devolve no chat).
    """
    from backend.graph.code_extractor import extract_snippets

    terms = [t.strip() for t in re.split(r"[\n,;]+", str(queries or "")) if t.strip()]
    res = extract_snippets(
        workspace_path=workspace_path,
        queries=terms,
        subpath=subpath,
        include_full_class=include_full_class,
        save_txt=save_txt,
    )
    if res.get("error"):
        return str(res["error"])
    if not res.get("blocks"):
        return str(res.get("summary") or "Nenhum trecho encontrado.")

    header = f"Encontrados **{len(res['blocks'])} trecho(s)** completo(s):\n{res['summary']}"
    if res.get("not_found"):
        header += "\n\nSem ocorrência: " + ", ".join(f"`{q}`" for q in res["not_found"])

    if res.get("txt_url") and res.get("txt_name"):
        link = f"[{res['txt_name']}]({res['txt_url']})"
        return (
            f"{header}\n\n"
            f"Arquivo `.txt` completo gerado (sem cortes): {link}\n\n"
            "INSTRUÇÕES DE FORMATAÇÃO:\n"
            f"1. Inclua o link EXATO `{link}` (com a barra inicial `/api/handoff/packs/...`, nunca troque por `api.handoff`).\n"
            "2. NÃO use tabelas Markdown largas nem listas genéricas de 'próximos passos'.\n"
            "3. Liste de forma curta e objetiva em tópicos (bullets) o que foi confirmado em cada arquivo/escopo e o que não teve ocorrência.\n\n"
            + res["formatted"][:14000]
        )

    return (
        f"{header}\n\n"
        "INSTRUÇÃO: entregue os trechos abaixo completos sem resumir nem cortar o código:\n\n"
        f"```text\n{res['formatted']}\n```"
    )


DEV_TOOLS = [run_safe_command, local_http_check, test_local_routes, docker_monitor_control, extract_code_snippets]
