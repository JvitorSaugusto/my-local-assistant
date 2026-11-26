"""Adaptadores finos e isolados entre `backend/autonomous` e o restante do `my-local-assistant`.

Este é o ÚNICO módulo de `backend/autonomous` que importa componentes de `backend/graph`.
Todas as dependências podem ser substituídas por implementações falsas em testes.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from .guards import is_protected_relative_path

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_SKIP_SCAN_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    ".next",
    "coverage",
    ".turbo",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".autonomous_data",
}
_JS_TS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_JS_EXPORT_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?"
    r"(?:(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|"
    r"class\s+([A-Za-z_$][\w$]*)|"
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)",
    re.MULTILINE,
)
_JS_ROUTE_RE = re.compile(
    r"""\b(?:app|router|fastify)\.(get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:type\s+)?(?:[^'"]+\s+from\s+)?|require\s*\(\s*)['"]([^'"]+)['"]"""
)
_BINARY_SEARCH_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip", ".rar",
    ".lock", ".pyc", ".woff", ".woff2", ".tar", ".gz", ".exe", ".dll", ".db", ".sqlite3",
}
_VENV_PYTHONS = (
    ".venv/Scripts/python.exe",
    "venv/Scripts/python.exe",
    ".venv/bin/python",
    "venv/bin/python",
)


@dataclass
class StepExecutionOutcome:
    ok: bool
    error: str | None = None
    report: str = ""
    warnings: list[str] = field(default_factory=list)


class LLMTextClient(Protocol):
    """Interface mínima de chamada de LLM (aceita ChatOllama ou stubs de teste)."""

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str: ...


class StepExecutorPort(Protocol):
    """Interface de execução determinística de microtasks (`steps` + `verify`)."""

    def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome: ...


class RepoInspectorPort(Protocol):
    """Interface somente leitura para inspecionar árvore, arquivos e rodar testes/lint."""

    def repo_overview(self, workspace_path: str, max_files: int = 120, max_chars: int = 8000) -> str: ...

    def read_files(self, workspace_path: str, rel_paths: list[str], max_chars_per_file: int = 8000) -> dict[str, str]: ...

    def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]: ...

    def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]: ...


def extract_json_payload(raw_text: str) -> Any:
    """Extrai JSON válido de respostas de LLMs locais (tolerando `<think>` e cercas markdown)."""
    cleaned = _THINK_TAG_RE.sub("", str(raw_text or "")).strip()
    if not cleaned:
        raise ValueError("Resposta vazia do modelo.")

    candidates: list[str] = [cleaned]
    for match in _CODE_FENCE_RE.finditer(cleaned):
        block = match.group(1).strip()
        if block:
            candidates.insert(0, block)

    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass

    # Fallback: recorta do primeiro '{' ou '[' até o último '}' ou ']'
    first_obj = cleaned.find("{")
    first_arr = cleaned.find("[")
    starts = [idx for idx in (first_obj, first_arr) if idx != -1]
    if starts:
        start = min(starts)
        opener = cleaned[start]
        closer = "}" if opener == "{" else "]"
        end = cleaned.rfind(closer)
        if end > start:
            return json.loads(cleaned[start : end + 1])

    raise ValueError("Nenhum bloco JSON válido encontrado na resposta do modelo.")


def invoke_structured_json(
    llm: LLMTextClient,
    *,
    role: str,
    system_prompt: str,
    user_prompt: str,
    schema_cls: type[BaseModel],
    max_repair_attempts: int = 2,
) -> Any:
    """Chama o LLM esperando JSON validado por Pydantic, com retry de reparo se o formato falhar."""
    last_error = ""
    current_user = user_prompt
    for attempt in range(max_repair_attempts + 1):
        raw = llm.complete(role, system_prompt, current_user)
        try:
            parsed = extract_json_payload(raw)
            return schema_cls.model_validate(parsed)
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            if attempt >= max_repair_attempts:
                break
            current_user = (
                f"{user_prompt}\n\n"
                f"ERRO NA RESPOSTA ANTERIOR: {last_error}\n"
                "Responda EXCLUSIVAMENTE com um objeto JSON válido seguindo exatamente o schema pedido, "
                "sem texto fora do JSON."
            )
    raise ValueError(f"Falha ao obter JSON válido ({schema_cls.__name__}): {last_error}")


def _workspace_python(root: Path) -> str:
    for candidate in _VENV_PYTHONS:
        full = root / candidate
        if full.is_file():
            return str(full)
    return sys.executable


class DefaultLLMClient:
    """Roteia chamadas por papel para os modelos locais configurados em `backend.graph.config`."""

    def __init__(self) -> None:
        self._last_model_name: str | None = None

    def _model_for_role(self, role: str):
        from backend.graph import config as graph_config

        mapping = {
            "planner": graph_config.heavy_llm,
            "coder": graph_config.generate_llm,
            "judge": graph_config.note_llm_final,
            "diagnostic": graph_config.code_llm,
        }
        return mapping.get(role, graph_config.generate_llm)

    def unload_model(self, model_name: str | None = None) -> None:
        """Libera VRAM no Ollama (keep_alive=0) ao trocar de fase ou pausar; nunca levanta erro."""
        target = model_name or self._last_model_name
        if not target:
            return
        base_url = (os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        for endpoint, body in (
            ("/api/generate", {"model": target, "prompt": "", "keep_alive": 0}),
            ("/api/chat", {"model": target, "messages": [], "keep_alive": 0}),
        ):
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}{endpoint}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=4):
                    break
            except Exception:  # noqa: BLE001 - liberação de VRAM é best-effort
                continue
        if target == self._last_model_name:
            self._last_model_name = None

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self._model_for_role(role)
        model_name = getattr(model, "model", None)
        if model_name and self._last_model_name and model_name != self._last_model_name:
            self.unload_model(self._last_model_name)

        response = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        if model_name:
            self._last_model_name = str(model_name)
        content = getattr(response, "content", "")
        if isinstance(content, list):
            parts = [str(p.get("text", p) if isinstance(p, dict) else p) for p in content]
            return "\n".join(parts)
        return str(content or "")


class DefaultStepExecutor:
    """Reaproveita `backend.graph.executor.execute_task_sync` (com idempotência, rollback e diff_review)."""

    def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome:
        from backend.graph.executor import execute_task_sync

        res = execute_task_sync(task_payload, workspace_path)
        warnings = [
            entry["detail"]
            for entry in res.log
            if entry.get("status") == "warn" and entry.get("detail")
        ]
        return StepExecutionOutcome(
            ok=res.ok,
            error=res.error,
            report=res.report(),
            warnings=warnings,
        )


class DefaultRepoInspector:
    """Inspeção segura e confinada ao workspace (sempre ignorando segredos e pastas pesadas)."""

    def repo_overview(self, workspace_path: str, max_files: int = 120, max_chars: int = 8000) -> str:
        root = Path(workspace_path).expanduser().resolve()
        if not root.is_dir():
            return "(workspace inexistente)"

        rel_files: list[str] = []
        for current, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_SCAN_DIRS and not d.startswith("."))
            for name in sorted(names):
                full = Path(current, name)
                rel = full.relative_to(root).as_posix()
                if is_protected_relative_path(rel):
                    continue
                rel_files.append(rel)
                if len(rel_files) >= max_files:
                    break
            if len(rel_files) >= max_files:
                break

        if not rel_files:
            return "(repositório vazio — projeto greenfield ou sem arquivos rastreáveis)"

        lines = [f"Arquivos do repositório ({len(rel_files)} listado(s)):"]
        for rel in rel_files:
            ext = Path(rel).suffix.lower()
            if ext == ".py":
                summary = self._py_compact_summary(root / rel)
            elif ext in _JS_TS_EXTS:
                summary = self._js_compact_summary(root / rel)
            else:
                summary = ""
            lines.append(f"- {rel}{summary}")
        output = "\n".join(lines)
        if len(output) > max_chars:
            output = output[:max_chars].rsplit("\n", 1)[0] + "\n[... lista truncada ...]"
        return output

    def _py_compact_summary(self, path: Path, max_symbols: int = 8) -> str:
        """Extrai rotas (@router/app.*) e assinaturas principais via AST para o planejador enxergar o código."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 120_000:
                return ""
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            return ""

        symbols: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols.append(f"class {node.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                route_hint = ""
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        method = dec.func.attr.lower()
                        if method in {"get", "post", "put", "patch", "delete", "api_route"}:
                            arg0 = dec.args[0] if dec.args else None
                            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                                route_hint = f" [{method.upper()} {arg0.value}]"
                                break
                symbols.append(f"{node.name}(){route_hint}")
            if len(symbols) >= max_symbols:
                break
        return f" — {', '.join(symbols)}" if symbols else ""

    def discover_related_files(
        self,
        workspace_path: str,
        target_files: list[str],
        max_related: int = 4,
    ) -> list[str]:
        """Descobre testes correspondentes e imports locais dos arquivos-alvo para dar contexto sem estourar janela."""
        root = Path(workspace_path).expanduser().resolve()
        if not root.is_dir():
            return []

        target_set = {str(p).strip().replace("\\", "/") for p in target_files if str(p).strip()}
        related: list[str] = []

        def add_if_exists(candidate: Path) -> None:
            if len(related) >= max_related or not candidate.is_file():
                return
            try:
                rel = candidate.resolve().relative_to(root).as_posix()
            except ValueError:
                return
            if rel in target_set or rel in related or is_protected_relative_path(rel):
                return
            related.append(rel)

        for rel in sorted(target_set):
            full = (root / rel).resolve()
            stem = Path(rel).stem
            parent = full.parent
            # 1. Testes correspondentes próximos
            for cand in (
                parent / f"test_{stem}.py",
                parent / "tests" / f"test_{stem}.py",
                parent.parent / "tests" / f"test_{stem}.py",
                root / "tests" / f"test_{stem}.py",
            ):
                add_if_exists(cand)

            # 2. Imports locais no arquivo Python
            if full.is_file() and full.suffix == ".py":
                try:
                    tree = ast.parse(full.read_text(encoding="utf-8", errors="replace"))
                except (OSError, SyntaxError):
                    continue
                for node in tree.body:
                    if len(related) >= max_related:
                        break
                    if isinstance(node, ast.ImportFrom) and node.module:
                        mod_rel = node.module.replace(".", "/")
                        add_if_exists(root / f"{mod_rel}.py")
                        if node.level > 0:
                            base = full.parent
                            for _ in range(node.level - 1):
                                base = base.parent
                            add_if_exists(base / f"{mod_rel}.py")
            elif full.is_file() and full.suffix.lower() in _JS_TS_EXTS:
                # 1b. Testes JS/TS/React correspondentes próximos
                for ext in (".test.tsx", ".test.ts", ".test.jsx", ".test.js", ".spec.tsx", ".spec.ts", ".spec.jsx", ".spec.js"):
                    add_if_exists(parent / f"{stem}{ext}")
                    add_if_exists(parent / "__tests__" / f"{stem}{ext}")
                    add_if_exists(root / "__tests__" / f"{stem}{ext}")
                # 2b. Imports relativos/alias (@/) em JS/TS/React
                try:
                    raw_js = full.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for imp_match in _JS_IMPORT_RE.finditer(raw_js):
                    if len(related) >= max_related:
                        break
                    spec = imp_match.group(1).strip()
                    base_cand: Path | None = None
                    if spec.startswith("."):
                        base_cand = parent / spec
                    elif spec.startswith("@/"):
                        rest = spec[2:]
                        base_cand = (root / "src" / rest) if (root / "src").is_dir() else (root / rest)
                    if base_cand is None:
                        continue
                    for trial in (
                        base_cand,
                        *(Path(str(base_cand) + e) for e in (".ts", ".tsx", ".js", ".jsx", ".mjs")),
                        *(base_cand / f"index{e}" for e in (".ts", ".tsx", ".js", ".jsx")),
                    ):
                        add_if_exists(trial)
        return related

    def _js_compact_summary(self, path: Path, max_symbols: int = 8) -> str:
        """Extrai componentes React, hooks, exports e rotas HTTP de arquivos JS/TS/JSX/TSX."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 120_000:
                return ""
        except OSError:
            return ""

        symbols: list[str] = []
        seen: set[str] = set()
        for rmatch in _JS_ROUTE_RE.finditer(text):
            tag = f"[{rmatch.group(1).upper()} {rmatch.group(2)}]"
            if tag not in seen:
                seen.add(tag)
                symbols.append(tag)
            if len(symbols) >= max_symbols:
                break

        for smatch in _JS_EXPORT_SYMBOL_RE.finditer(text):
            name = smatch.group(1) or smatch.group(2) or smatch.group(3) or ""
            if not name or name in seen:
                continue
            seen.add(name)
            if smatch.group(2):
                symbols.append(f"class {name}")
            elif name[0].isupper() and path.suffix.lower() in {".jsx", ".tsx"}:
                symbols.append(f"<{name} />")
            elif name.startswith("use") and len(name) > 3 and name[3].isupper():
                symbols.append(f"hook {name}()")
            else:
                symbols.append(f"{name}()")
            if len(symbols) >= max_symbols:
                break
        return f" — {', '.join(symbols)}" if symbols else ""

    def detect_project_stacks(self, workspace_path: str, touched_files: list[str] | None = None) -> set[str]:
        """Detecta stacks ativas no projeto (`python`, `js`, `ts`, `react`)."""
        root = Path(workspace_path).expanduser().resolve()
        stacks: set[str] = set()
        if not root.is_dir():
            return stacks

        if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file() or (root / "pytest.ini").is_file():
            stacks.add("python")
        if (root / "tsconfig.json").is_file():
            stacks.update({"js", "ts"})

        pkg_json = root / "package.json"
        if pkg_json.is_file():
            stacks.add("js")
            try:
                pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
                deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
                if "typescript" in deps:
                    stacks.add("ts")
                if any(k in deps for k in ("react", "react-dom", "next", "preact")):
                    stacks.add("react")
            except (OSError, json.JSONDecodeError):
                pass

        for rel in touched_files or []:
            ext = Path(str(rel)).suffix.lower()
            if ext == ".py":
                stacks.add("python")
            elif ext in {".ts", ".tsx"}:
                stacks.update({"js", "ts"})
                if ext == ".tsx":
                    stacks.add("react")
            elif ext in {".js", ".jsx", ".mjs", ".cjs"}:
                stacks.add("js")
                if ext == ".jsx":
                    stacks.add("react")
        return stacks

    def search_text(self, workspace_path: str, queries: list[str], max_hits: int = 30) -> str:
        """Busca rápida e somente leitura de símbolos/rotas/trechos no workspace (para micro-investigação do Coder)."""
        root = Path(workspace_path).expanduser().resolve()
        clean_queries = [str(q).strip() for q in (queries or []) if str(q).strip()][:6]
        if not root.is_dir() or not clean_queries:
            return ""

        hits: list[str] = []
        lowered = [q.lower() for q in clean_queries]
        for current, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_SCAN_DIRS and not d.startswith("."))
            for name in sorted(names):
                if len(hits) >= max_hits:
                    break
                full = Path(current, name)
                if full.suffix.lower() in _BINARY_SEARCH_EXTS:
                    continue
                rel = full.relative_to(root).as_posix()
                if is_protected_relative_path(rel):
                    continue
                try:
                    raw = full.read_bytes()
                except OSError:
                    continue
                if len(raw) > 512 * 1024 or b"\0" in raw[:4000]:
                    continue
                text = raw.decode("utf-8", errors="replace")
                low_text = text.lower()
                if not any(q in low_text for q in lowered):
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    low_line = line.lower()
                    if any(q in low_line for q in lowered):
                        hits.append(f"{rel}:{line_no}: {line.strip()[:180]}")
                        if len(hits) >= max_hits:
                            break
            if len(hits) >= max_hits:
                break
        return "\n".join(hits)

    def _local_node_bin(self, root: Path, name: str) -> str | None:
        candidates = (
            root / "node_modules" / ".bin" / f"{name}.cmd",
            root / "node_modules" / ".bin" / name,
        )
        for cand in candidates:
            if cand.is_file():
                return str(cand)
        return None

    def _js_bracket_sanity(self, rel: str, source: str) -> str | None:
        """Checagem leve de balanceamento de `{}`, `()` e `[]` ignorando comentários e strings simples."""
        stack: list[tuple[str, int]] = []
        pairs = {")": "(", "]": "[", "}": "{"}
        in_str: str | None = None
        in_block_comment = False
        in_line_comment = False
        escaped = False
        line_no = 1
        i = 0
        n = len(source)
        while i < n:
            ch = source[i]
            nxt = source[i + 1] if i + 1 < n else ""
            if ch == "\n":
                line_no += 1
                in_line_comment = False
                if in_str in ("'", '"'):
                    in_str = None
                escaped = False
                i += 1
                continue
            if in_line_comment:
                i += 1
                continue
            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_str:
                    in_str = None
                i += 1
                continue
            if ch == "/" and nxt == "/":
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue
            if ch in ("'", '"', "`"):
                in_str = ch
                i += 1
                continue
            if ch in "([{":
                stack.append((ch, line_no))
            elif ch in ")]}":
                if not stack or stack[-1][0] != pairs[ch]:
                    return f"{rel}: delimitador '{ch}' inesperado perto da linha {line_no}"
                stack.pop()
            i += 1
        if stack:
            opener, open_line = stack[-1]
            return f"{rel}: delimitador '{opener}' aberto na linha {open_line} não foi fechado"
        return None

    def run_js_ts_syntax(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
        """Valida sintaxe JS (`node --check`), balanceamento JSX/TSX e typecheck (`tsc --noEmit`)."""
        js_ts_files = [
            p for p in rel_paths
            if Path(p).suffix.lower() in _JS_TS_EXTS and not is_protected_relative_path(p)
        ]
        if not js_ts_files:
            return True, "Sem arquivos JS/TS para validar."

        root = Path(workspace_path).expanduser().resolve()
        errors: list[str] = []

        # 1. Checagem de sintaxe/balanceamento arquivo a arquivo
        for rel in js_ts_files:
            full = (root / rel).resolve()
            if not full.is_file():
                continue
            ext = full.suffix.lower()
            text = full.read_text(encoding="utf-8", errors="replace")
            if ext in {".js", ".mjs", ".cjs"} and not re.search(r"<[A-Za-z][A-Za-z0-9]*[\s/>]", text):
                try:
                    done = subprocess.run(
                        ["node", "--check", str(full)],
                        cwd=str(root),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=20,
                    )
                    if done.returncode != 0:
                        detail = (done.stderr or done.stdout or "").strip()[:400]
                        errors.append(f"node --check falhou em '{rel}': {detail}")
                except (OSError, subprocess.TimeoutExpired):
                    bal = self._js_bracket_sanity(rel, text)
                    if bal:
                        errors.append(bal)
            else:
                bal = self._js_bracket_sanity(rel, text)
                if bal:
                    errors.append(bal)

        # 2. Typecheck TypeScript (tsc --noEmit) se houver tsconfig.json e arquivos .ts/.tsx
        has_ts = any(Path(p).suffix.lower() in {".ts", ".tsx"} for p in js_ts_files)
        if has_ts and (root / "tsconfig.json").is_file():
            tsc_bin = self._local_node_bin(root, "tsc")
            cmd = [tsc_bin, "--noEmit"] if tsc_bin else ["npx", "--no-install", "tsc", "--noEmit"]
            try:
                done = subprocess.run(
                    cmd,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                combined = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else "")).strip()
                if done.returncode != 0 and "not found" not in combined.lower() and "could not determine executable" not in combined.lower():
                    errors.append(f"tsc --noEmit falhou:\n{combined[:2500]}")
            except (OSError, subprocess.TimeoutExpired):
                pass

        if errors:
            return False, "\n".join(errors)
        return True, f"Sintaxe JS/TS/React OK ({len(js_ts_files)} arquivo(s))."

    def run_eslint(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
        js_ts_files = [
            p for p in rel_paths
            if Path(p).suffix.lower() in _JS_TS_EXTS and not is_protected_relative_path(p)
        ]
        if not js_ts_files:
            return True, "Sem arquivos JS/TS para eslint."
        root = Path(workspace_path).expanduser().resolve()
        existing = [p for p in js_ts_files if (root / p).is_file()]
        eslint_bin = self._local_node_bin(root, "eslint")
        if not existing or not eslint_bin:
            return True, "eslint indisponível no projeto (ignorado)."
        try:
            done = subprocess.run(
                [eslint_bin, "--no-color", *existing],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True, "eslint indisponível (ignorado)."
        combined = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else "")).strip()
        if done.returncode == 0:
            return True, "eslint OK."
        return False, combined[:3000]

    def run_js_tests(self, workspace_path: str) -> tuple[bool, str]:
        """Executa testes JS/TS/React (Vitest/Jest/npm test) se configurados em package.json."""
        root = Path(workspace_path).expanduser().resolve()
        pkg_path = root / "package.json"
        if not pkg_path.is_file():
            return True, "Sem package.json (testes JS não aplicáveis)."
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return True, "package.json ilegível (ignorado)."

        scripts = pkg.get("scripts") or {}
        test_script = str(scripts.get("test") or "").strip()
        if not test_script or "no test specified" in test_script.lower():
            return True, "Nenhum script de teste configurado em package.json."

        low_script = test_script.lower()
        vitest_bin = self._local_node_bin(root, "vitest")
        jest_bin = self._local_node_bin(root, "jest")
        if "vitest" in low_script and vitest_bin:
            cmd = [vitest_bin, "run"]
        elif "jest" in low_script and jest_bin:
            cmd = [jest_bin, "--ci", "--watchAll=false"]
        else:
            npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
            cmd = [npm_cmd, "test", "--", "--watchAll=false"]

        try:
            done = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=int(os.getenv("AUTONOMOUS_JS_TEST_TIMEOUT", "") or 180),
                env={**os.environ, "CI": "true"},
            )
        except subprocess.TimeoutExpired:
            return False, "Testes JS/TS excederam o tempo limite."
        except OSError as exc:
            return True, f"Runner JS/TS indisponível no ambiente ({exc}); ignorado."

        output = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else "")).strip()
        if len(output) > 4000:
            output = "[...]\n" + output[-4000:]
        if done.returncode == 0:
            return True, output or "Testes JS/TS passaram."
        return False, output or f"Testes JS/TS falharam (código {done.returncode})."

    def read_files(
        self,
        workspace_path: str,
        rel_paths: list[str],
        max_chars_per_file: int = 8000,
    ) -> dict[str, str]:
        root = Path(workspace_path).expanduser().resolve()
        contents: dict[str, str] = {}
        for rel in rel_paths:
            clean = str(rel or "").strip().replace("\\", "/")
            if not clean or is_protected_relative_path(clean):
                continue
            full = (root / clean).resolve()
            try:
                full.relative_to(root)
            except ValueError:
                continue
            if not full.is_file():
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > max_chars_per_file:
                text = text[:max_chars_per_file] + "\n[... arquivo truncado ...]"
            contents[clean] = text
        return contents

    def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]:
        root = Path(workspace_path).expanduser().resolve()
        python = _workspace_python(root)
        cmd = [python, "-m", "pytest", "-q", "--tb=short", "--no-header", "--maxfail=15", "-p", "no:cacheprovider"]
        if target and not target.startswith("-"):
            cmd.append(target)
        try:
            done = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=int(os.getenv("AUTONOMOUS_PYTEST_TIMEOUT", "") or 180),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired:
            return False, "pytest excedeu o tempo limite."
        except OSError as exc:
            return False, f"erro ao executar pytest: {exc}"

        output = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else "")).strip()
        if len(output) > 4000:
            output = "[...]\n" + output[-4000:]
        # Código 5 = nenhum teste coletado (não bloqueia projetos ainda sem testes)
        if done.returncode in (0, 5):
            return True, output or ("Nenhum teste coletado." if done.returncode == 5 else "Todos os testes passaram.")
        return False, output or f"pytest falhou (código {done.returncode})."

    def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
        py_files = [p for p in rel_paths if p.endswith(".py") and not is_protected_relative_path(p)]
        if not py_files:
            return True, "Sem arquivos Python para ruff."
        root = Path(workspace_path).expanduser().resolve()
        existing = [p for p in py_files if (root / p).is_file()]
        if not existing:
            return True, "Sem arquivos Python existentes para ruff."
        python = _workspace_python(root)
        try:
            done = subprocess.run(
                [python, "-m", "ruff", "check", "--no-fix", *existing],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True, "ruff indisponível (ignorado)."

        combined = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else "")).strip()
        if "No module named ruff" in combined:
            return True, "ruff não instalado no ambiente (ignorado)."
        if done.returncode == 0:
            return True, "ruff OK."
        return False, combined[:3000]
