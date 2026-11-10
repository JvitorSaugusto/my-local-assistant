"""Dry-run de tasks (Fase A): aplica as tasks numa CÓPIA temporária, com o executor real, antes de valer.

Só copia os arquivos que as tasks citam, cria um repositório git descartável numa branch de trabalho
e roda `execute_task_sync` em ordem (como o despacho: se uma falha, as seguintes ficam bloqueadas).
O resultado é um relatório curto, pronto para colar na IA externa, com o motivo e o trecho REAL do
arquivo ao redor do `old` que não casou, para ela corrigir sem você reenviar o arquivo inteiro.
O workspace verdadeiro nunca é alterado.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

_ERR_LIMIT = 800
_RADIUS = 12


def normalize_tasks(raw: Any) -> list[dict]:
    """Aceita lista, {"tasks": [...]}, uma task solta ou texto JSON."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido (linha {exc.lineno}, coluna {exc.colno}): {exc.msg}") from exc
    if isinstance(raw, dict):
        raw = raw.get("tasks", [raw])
    if not isinstance(raw, list) or not raw or not all(isinstance(t, dict) for t in raw):
        raise ValueError("Esperava uma lista de tasks (objetos JSON).")
    return raw


def _referenced_paths(tasks: list[dict]) -> list[str]:
    paths: list[str] = []
    for task in tasks:
        for item in list(task.get("steps") or []) + list(task.get("verify") or []):
            p = item.get("path") if isinstance(item, dict) else None
            if isinstance(p, str) and p.strip() and p.strip() not in paths:
                paths.append(p.strip().replace("\\", "/"))
    return paths


def _copy_subset(root: Path, tmp: Path, rels: list[str]) -> None:
    for rel in rels:
        try:
            src = (root / rel).resolve()
            src.relative_to(root)
        except ValueError:
            continue  # fora do projeto: o executor vai recusar de qualquer jeito
        if src.is_file():
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=dryrun@local", "-c", "user.name=dryrun", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def _excerpt(text: str, old: str) -> str:
    """Onde o `old` deveria estar: primeira diferença e linhas numeradas ao redor."""
    lines = text.split("\n")
    old_lines = old.replace("\r\n", "\n").split("\n")
    probe = next((l.strip() for l in old_lines if l.strip()), "")
    if not probe:
        return "(o `old` está vazio)"
    stripped = [l.strip() for l in lines]
    exact = [i for i, l in enumerate(stripped) if l == probe]
    if exact:
        idx = exact[0]
    else:
        close = difflib.get_close_matches(probe, stripped, n=1, cutoff=0.5)
        if not close:
            return "(nenhuma linha parecida com o início do `old` foi encontrada no arquivo)"
        idx = stripped.index(close[0])
    first = next((i for i, l in enumerate(old_lines) if l.strip()), 0)
    start = max(0, idx - first)
    note = ""
    for offset, expected in enumerate(old_lines):
        actual = lines[start + offset] if start + offset < len(lines) else "<fim do arquivo>"
        if expected.rstrip() != actual.rstrip():
            note = f"1ª diferença (linha {start + offset + 1}):\n  esperado: {expected!r}\n  no arquivo: {actual!r}\n"
            break
    lo, hi = max(0, idx - _RADIUS), min(len(lines), idx + _RADIUS + len(old_lines))
    body = "\n".join(f"{n + 1}: {lines[n]}" for n in range(lo, hi))
    return note + body


def _default_runner(task: dict, workspace: str, thread_id: str | None):
    from backend.graph.executor import execute_task_sync  # import tardio: só quando o dry-run é pedido

    return execute_task_sync(task, workspace, thread_id)


async def dry_run_tasks(
    workspace: str,
    raw_tasks: Any,
    runner: Callable[[dict, str, str | None], Any] | None = None,
    thread_id: str | None = None,
) -> dict:
    tasks = normalize_tasks(raw_tasks)
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Pasta não encontrada: {workspace}")
    run = runner or _default_runner
    results: list[dict] = []
    blocked_by: int | None = None

    with tempfile.TemporaryDirectory(prefix="dryrun_") as tmp_name:
        tmp = Path(tmp_name)
        _copy_subset(root, tmp, _referenced_paths(tasks))
        setup = [_git(tmp, "init", "-q"), _git(tmp, "add", "-A"), _git(tmp, "commit", "-qm", "base", "--allow-empty"),
                 _git(tmp, "checkout", "-q", "-b", "dryrun")]
        if any(p.returncode != 0 for p in setup):
            bad = next(p for p in setup if p.returncode != 0)
            raise ValueError(f"não foi possível preparar a cópia de teste (git): {bad.stderr.strip()[:300]}")

        for number, task in enumerate(tasks, start=1):
            entry: dict = {"index": number, "title": str(task.get("title", f"task {number}")), "status": "ok"}
            if blocked_by is not None:
                entry.update(status="blocked", error=f"não testada: a task #{blocked_by} falhou antes.")
                results.append(entry)
                continue
            try:
                outcome = await asyncio.to_thread(run, task, str(tmp), thread_id)
            except Exception as exc:  # noqa: BLE001
                outcome = None
                entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            else:
                if not outcome.ok:
                    entry.update(status="failed", error=(outcome.error or "falha desconhecida"),
                                 failed_step=outcome.failed_step)
                    steps = task.get("steps") or []
                    step = steps[outcome.failed_step - 1] if outcome.failed_step and outcome.failed_step <= len(steps) else None
                    if isinstance(step, dict) and step.get("op") == "replace_text":
                        target = tmp / str(step.get("path", ""))
                        if target.is_file():
                            entry["excerpt"] = _excerpt(_read(target), str(step.get("old", "")))
                            entry["excerpt_path"] = step.get("path")
            if entry["status"] == "failed":
                blocked_by = number
            results.append(entry)

    ok = sum(r["status"] == "ok" for r in results)
    failed = sum(r["status"] == "failed" for r in results)
    blocked = sum(r["status"] == "blocked" for r in results)
    lines = [f"# Dry-run de {len(results)} task(s): {ok} ok, {failed} com falha, {blocked} bloqueada(s)"]
    for r in results:
        icon = {"ok": "✅", "failed": "❌", "blocked": "⏸️"}[r["status"]]
        lines.append(f"\n{icon} #{r['index']} {r['title']}")
        if r["status"] == "ok":
            continue
        lines.append(r["error"][:_ERR_LIMIT])
        if r.get("excerpt"):
            lines.append(f"\nTrecho REAL de `{r['excerpt_path']}` onde o `old` deveria estar:\n```\n{r['excerpt']}\n```")
    if failed:
        lines.append(
            "\nCorrija SÓ as tasks com ❌ (e reenvie as bloqueadas se dependiam delas). Copie o `old` literalmente "
            "do trecho real acima; não reescreva de memória."
        )
    return {"ok": failed == 0, "summary": {"ok": ok, "failed": failed, "blocked": blocked},
            "results": results, "report": "\n".join(lines)}
