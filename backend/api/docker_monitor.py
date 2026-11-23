"""Monitor determinístico em background para Docker Compose (logs, build e alertas no chat).

Custo zero de VRAM enquanto vigia: um processo `docker compose logs -f` roda em asyncio,
agrupa tracebacks/erros com debounce e só aciona o chat/LLM quando um erro real aparece.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

ERROR_PATTERNS = re.compile(
    r"(Traceback \(most recent call last\):|"
    r"\b(?:ModuleNotFoundError|ImportError|SyntaxError|IndentationError|NameError|"
    r"AttributeError|TypeError|ValueError|KeyError|RuntimeError|OperationalError|"
    r"ProgrammingError|IntegrityError|ConnectionRefusedError)\b|"
    r"\b(?:CRITICAL|FATAL)\b|"
    r"exited with code [1-9]\d*|"
    r"failed to solve|"
    r"Cannot find module|"
    r"error TS\d{4}:|"
    r"ERROR:\s+Application startup failed)",
    re.IGNORECASE,
)

TRACEBACK_FILE_RE = re.compile(r'File "([^"]+)", line (\d+)')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_ws(workspace_path: str) -> str:
    return str(Path(workspace_path).expanduser().resolve())


def is_error_line(line: str) -> bool:
    return bool(ERROR_PATTERNS.search(line or ""))


def extract_code_snippet_from_traceback(workspace: str, error_block: str) -> str:
    """Tenta localizar o último arquivo do workspace citado num traceback Python e ler o entorno."""
    root = Path(workspace).resolve()
    matches = TRACEBACK_FILE_RE.findall(error_block or "")
    for raw_path, line_str in reversed(matches):
        try:
            line_no = int(line_str)
        except ValueError:
            continue
        candidates = [Path(raw_path)]
        norm = raw_path.replace("\\", "/")
        for marker in ("/app/", "/code/", "/src/", "/backend/"):
            if marker in norm:
                rel = norm.split(marker, 1)[1]
                candidates.append(root / rel)
                candidates.append(root / marker.strip("/") / rel)
        for cand in candidates:
            try:
                resolved = cand.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if resolved.is_file():
                try:
                    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
                    start = max(1, line_no - 6)
                    end = min(len(lines), line_no + 6)
                    excerpt = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
                    rel_display = resolved.relative_to(root).as_posix()
                    return f"Trecho de `{rel_display}` (linha {line_no}):\n```python\n{excerpt}\n```"
                except OSError:
                    continue
    return ""


@dataclass
class MonitorSession:
    workspace_path: str
    thread_id: str
    auto_diagnose: bool = True
    started_at: str = field(default_factory=_now_iso)
    running: bool = False
    building: bool = False
    last_build_seconds: float | None = None
    last_build_at: str | None = None
    last_build_ok: bool | None = None
    lines_seen: int = 0
    errors_detected: int = 0
    last_error: dict[str, Any] | None = None
    recent_logs: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    task: asyncio.Task | None = None
    process: asyncio.subprocess.Process | None = None
    _last_alert_sig: str = ""
    _last_alert_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_path": self.workspace_path,
            "project_name": Path(self.workspace_path).name,
            "thread_id": self.thread_id,
            "auto_diagnose": self.auto_diagnose,
            "started_at": self.started_at,
            "running": self.running,
            "building": self.building,
            "last_build_seconds": self.last_build_seconds,
            "last_build_at": self.last_build_at,
            "last_build_ok": self.last_build_ok,
            "lines_seen": self.lines_seen,
            "errors_detected": self.errors_detected,
            "last_error": self.last_error,
            "recent_logs": list(self.recent_logs)[-30:],
        }


class DockerMonitorManager:
    def __init__(self) -> None:
        self._sessions: dict[str, MonitorSession] = {}
        self._app_graph: Any = None

    def bind_graph(self, app_graph: Any) -> None:
        self._app_graph = app_graph

    def get_session(self, workspace_path: str) -> MonitorSession | None:
        if not workspace_path or not workspace_path.strip():
            return None
        return self._sessions.get(_norm_ws(workspace_path))

    def status_all(self, workspace_path: str = "") -> dict[str, Any]:
        active = None
        if workspace_path and workspace_path.strip():
            sess = self.get_session(workspace_path)
            if sess:
                active = sess.to_dict()
        return {
            "active": active,
            "monitors": [s.to_dict() for s in self._sessions.values()],
        }

    async def start(
        self,
        workspace_path: str,
        thread_id: str,
        auto_diagnose: bool = True,
        app_graph: Any = None,
    ) -> dict[str, Any]:
        if app_graph is not None:
            self._app_graph = app_graph
        root = Path(workspace_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Diretório não encontrado: {workspace_path}")
        key = str(root)
        existing = self._sessions.get(key)
        if existing and existing.running:
            existing.thread_id = thread_id or existing.thread_id
            existing.auto_diagnose = auto_diagnose
            return existing.to_dict()

        session = existing or MonitorSession(workspace_path=key, thread_id=thread_id, auto_diagnose=auto_diagnose)
        session.thread_id = thread_id or session.thread_id
        session.auto_diagnose = auto_diagnose
        session.started_at = _now_iso()
        session.running = True
        self._sessions[key] = session
        session.task = asyncio.create_task(self._watch_loop(session))
        return session.to_dict()

    async def stop(self, workspace_path: str) -> dict[str, Any]:
        key = _norm_ws(workspace_path)
        session = self._sessions.get(key)
        if not session:
            return {"stopped": False, "message": "Nenhum monitor ativo para este projeto."}
        session.running = False
        if session.process and session.process.returncode is None:
            try:
                session.process.terminate()
            except ProcessLookupError:
                pass
        if session.task and not session.task.done():
            session.task.cancel()
            try:
                await session.task
            except (asyncio.CancelledError, Exception):
                pass
        return {"stopped": True, "monitor": session.to_dict()}

    async def _post_to_chat(self, thread_id: str, content: str) -> None:
        if not thread_id or self._app_graph is None:
            return
        config = {"configurable": {"thread_id": thread_id}}
        msg = AIMessage(
            content=content,
            name="Monitor Docker",
            additional_kwargs={"message_tag": "monitor_alert", "created_at": _now_iso()},
        )
        try:
            await self._app_graph.aupdate_state(config, {"messages": [msg]})
        except Exception:
            try:
                await self._app_graph.aupdate_state(config, {"messages": [msg]}, as_node="__start__")
            except Exception as exc:  # noqa: BLE001
                print(f"[MONITOR] Falha ao postar alerta no chat {thread_id}: {exc}")

    async def _diagnose_error(self, session: MonitorSession, error_block: str) -> str:
        snippet = extract_code_snippet_from_traceback(session.workspace_path, error_block)
        if not session.auto_diagnose:
            return snippet

        try:
            from backend.graph.config import code_llm

            prompt = (
                f"Projeto: {Path(session.workspace_path).name}\n\n"
                f"Erro capturado nos logs do Docker Compose:\n```\n{error_block[:3000]}\n```\n\n"
                + (f"{snippet}\n\n" if snippet else "")
                + "Responda em português, de forma direta e curta (máximo 8 linhas):\n"
                "1. **Causa provável:** o que quebrou e por quê.\n"
                "2. **Correção sugerida:** o ajuste exato a fazer."
            )
            resp = await asyncio.to_thread(
                code_llm.invoke,
                [
                    SystemMessage(content="Você é um engenheiro sênior analisando um erro real de container Docker. Seja objetivo e técnico."),
                    HumanMessage(content=prompt),
                ],
            )
            text = str(getattr(resp, "content", "") or "").strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            print(f"[MONITOR] Diagnóstico via LLM indisponível: {exc}")
        return snippet

    async def _emit_error_alert(self, session: MonitorSession, lines: list[str]) -> None:
        block = "\n".join(lines).strip()
        if not block:
            return
        sig = block[:220]
        now = time.monotonic()
        if sig == session._last_alert_sig and (now - session._last_alert_ts) < 20.0:
            return
        session._last_alert_sig = sig
        session._last_alert_ts = now
        session.errors_detected += 1

        diagnosis = await self._diagnose_error(session, block)
        session.last_error = {
            "at": _now_iso(),
            "excerpt": block[:2000],
            "diagnosis": diagnosis[:2000],
        }

        project = Path(session.workspace_path).name
        parts = [
            f"### Alerta do Monitor Docker (`{project}`)",
            f"```text\n{block[:1600]}\n```",
        ]
        if diagnosis:
            parts.append(diagnosis)
        parts.append(
            "Quer que eu **gere as tasks de correção** (responda com `@heavy gere as tasks para corrigir o erro acima`) ou você mesmo vai corrigir?"
        )
        await self._post_to_chat(session.thread_id, "\n\n".join(parts))

    async def _watch_loop(self, session: MonitorSession) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "logs", "-f", "--tail=15", "--no-color",
                cwd=session.workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            session.process = proc
        except Exception as exc:  # noqa: BLE001
            session.running = False
            session.last_error = {"at": _now_iso(), "excerpt": f"Falha ao iniciar docker compose logs: {exc}", "diagnosis": ""}
            return

        buf: list[str] = []
        capturing = False
        last_line_ts = 0.0

        try:
            assert proc.stdout is not None
            while session.running:
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), timeout=1.5)
                except asyncio.TimeoutError:
                    if capturing and buf and (time.monotonic() - last_line_ts) >= 2.2:
                        await self._emit_error_alert(session, buf)
                        buf, capturing = [], False
                    if proc.returncode is not None:
                        break
                    continue

                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                session.lines_seen += 1
                session.recent_logs.append(line)

                if is_error_line(line):
                    capturing = True
                    buf.append(line)
                    last_line_ts = time.monotonic()
                elif capturing:
                    buf.append(line)
                    last_line_ts = time.monotonic()
                    if len(buf) >= 35:
                        await self._emit_error_alert(session, buf)
                        buf, capturing = [], False

            if capturing and buf:
                await self._emit_error_alert(session, buf)
        except asyncio.CancelledError:
            raise
        finally:
            session.running = False
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

    async def run_build(
        self,
        workspace_path: str,
        thread_id: str,
        app_graph: Any = None,
    ) -> dict[str, Any]:
        """Executa `docker compose up -d --build` em background, mede o tempo e avisa no chat."""
        if app_graph is not None:
            self._app_graph = app_graph
        root = Path(workspace_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Diretório não encontrado: {workspace_path}")
        key = str(root)
        session = self._sessions.get(key) or MonitorSession(workspace_path=key, thread_id=thread_id)
        session.thread_id = thread_id or session.thread_id
        self._sessions[key] = session

        if session.building:
            return {"started": False, "message": "Já existe um build em andamento para este projeto.", "monitor": session.to_dict()}

        session.building = True
        asyncio.create_task(self._build_job(session))
        return {"started": True, "message": "Build do Docker Compose iniciado em background.", "monitor": session.to_dict()}

    async def _build_job(self, session: MonitorSession) -> None:
        started = time.perf_counter()
        project = Path(session.workspace_path).name
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "up", "-d", "--build",
                cwd=session.workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            elapsed = round(time.perf_counter() - started, 1)
            session.last_build_seconds = elapsed
            session.last_build_at = _now_iso()
            session.last_build_ok = proc.returncode == 0

            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            tail = "\n".join(output.splitlines()[-30:])
            if proc.returncode == 0:
                await self._post_to_chat(
                    session.thread_id,
                    f"### Build Docker concluído (`{project}`)\n\n"
                    f"Tempo total: **{elapsed} s** (`docker compose up -d --build`). Todos os serviços subiram sem erro.",
                )
            else:
                diagnosis = await self._diagnose_error(session, tail)
                session.errors_detected += 1
                session.last_error = {"at": _now_iso(), "excerpt": tail[:2000], "diagnosis": diagnosis[:2000]}
                msg = (
                    f"### Falha no Build Docker (`{project}` · {elapsed} s)\n\n"
                    f"```text\n{tail[:1600]}\n```\n\n"
                    + (f"{diagnosis}\n\n" if diagnosis else "")
                    + "Quer que eu gere as tasks de correção ou você mesmo vai corrigir?"
                )
                await self._post_to_chat(session.thread_id, msg)
        except Exception as exc:  # noqa: BLE001
            session.last_build_ok = False
            await self._post_to_chat(session.thread_id, f"### Erro ao executar build Docker (`{project}`)\n\n{exc}")
        finally:
            session.building = False


monitor_manager = DockerMonitorManager()
