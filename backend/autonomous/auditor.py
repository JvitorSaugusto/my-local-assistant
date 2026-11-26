"""Auditoria objetiva (determinística): sintaxe AST, ruff, pytest e guarda anti-trapaça."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import RepoInspectorPort
from .guards import GitMissionSandbox, detect_test_tampering, is_protected_relative_path, is_test_file_path
from .schemas import MissionMode, MissionRecord


@dataclass
class AuditReport:
    passed: bool
    files_checked: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    test_summary: str = ""
    lint_summary: str = ""

    def to_short_text(self) -> str:
        status = "APROVADA" if self.passed else "REPROVADA"
        lines = [f"Auditoria objetiva: {status} ({len(self.files_checked)} arquivo(s) verificado(s))."]
        if self.test_summary:
            lines.append(f"Testes: {self.test_summary[:400]}")
        if self.lint_summary:
            lines.append(f"Lint: {self.lint_summary[:300]}")
        if self.blocking_issues:
            lines.append("Bloqueios:")
            lines.extend(f"- {item}" for item in self.blocking_issues)
        if self.warnings:
            lines.append("Avisos:")
            lines.extend(f"- {item}" for item in self.warnings)
        return "\n".join(lines)


def _changed_since_base(sandbox: GitMissionSandbox, base_commit: str | None) -> list[str]:
    if not base_commit:
        return sandbox.changed_files()
    res = sandbox._run_git("diff", "--name-only", f"{base_commit}..HEAD", check=False)
    committed = [ln.strip().replace("\\", "/") for ln in res.stdout.splitlines() if ln.strip()]
    working = sandbox.changed_files()
    return sorted(dict.fromkeys(committed + working))


def _snapshot_at_commit(sandbox: GitMissionSandbox, commit: str, rel_paths: list[str]) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for rel in rel_paths:
        res = sandbox._run_git("show", f"{commit}:{rel}", check=False)
        snap[rel] = res.stdout if res.returncode == 0 else None
    return snap


def run_objective_audit(
    mission: MissionRecord,
    inspector: RepoInspectorPort,
    sandbox: GitMissionSandbox | None = None,
    *,
    extra_files: list[str] | None = None,
    run_tests: bool = True,
) -> AuditReport:
    """Executa verificações determinísticas no repositório sem depender de opinião do LLM."""
    blocking: list[str] = []
    warnings: list[str] = []

    if mission.mode == MissionMode.DIAGNOSTIC_ONLY:
        if sandbox is not None and not sandbox.is_clean():
            blocking.append("Modo diagnóstico (somente leitura) deixou alterações pendentes no workspace.")
        return AuditReport(
            passed=not blocking,
            files_checked=[],
            blocking_issues=blocking,
            warnings=warnings,
            test_summary="Modo diagnóstico: testes de edição não aplicáveis.",
            lint_summary="Modo diagnóstico: somente leitura.",
        )

    files: list[str] = []
    if sandbox is not None:
        files.extend(_changed_since_base(sandbox, mission.base_commit))
    if extra_files:
        files.extend(str(f).strip().replace("\\", "/") for f in extra_files if str(f).strip())
    files = sorted(dict.fromkeys(files))

    root = Path(mission.workspace_path).expanduser().resolve()

    # 1. Segurança de caminhos + sintaxe AST Python
    for rel in files:
        if is_protected_relative_path(rel):
            blocking.append(f"Arquivo protegido tocado pela missão: '{rel}'.")
            continue
        full = (root / rel).resolve()
        if not full.is_file():
            continue
        if rel.endswith(".py"):
            try:
                ast.parse(full.read_text(encoding="utf-8", errors="replace"), filename=rel)
            except SyntaxError as exc:
                blocking.append(f"Erro de sintaxe em '{rel}' linha {exc.lineno}: {exc.msg}")

    # 2. Guarda anti-trapaça acumulada contra o commit base
    if sandbox is not None and mission.base_commit and files:
        before = _snapshot_at_commit(sandbox, mission.base_commit, files)
        after = sandbox.snapshot_working_files(files)
        tamper = detect_test_tampering(
            before,
            after,
            allow_test_deletion=mission.config.allow_test_deletion,
        )
        if not tamper.ok:
            blocking.extend(tamper.violations)

    detect_fn = getattr(inspector, "detect_project_stacks", None)
    stacks = detect_fn(mission.workspace_path, files) if callable(detect_fn) else {"python"}
    has_js_ts_files = any(Path(f).suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"} for f in files)
    has_py_files = any(f.endswith(".py") for f in files)

    # 2b. Sintaxe e Typecheck JS/TS/React (node --check, balanceamento JSX/TSX e tsc --noEmit)
    if has_js_ts_files:
        js_syntax_fn = getattr(inspector, "run_js_ts_syntax", None)
        if callable(js_syntax_fn):
            js_ok, js_msg = js_syntax_fn(mission.workspace_path, files)
            if not js_ok:
                blocking.append(js_msg)

    # 3. Lint opcional (ruff para Python + eslint para JS/TS/React)
    lint_parts: list[str] = []
    if has_py_files or "python" in stacks:
        lint_ok, ruff_summary = inspector.run_ruff(mission.workspace_path, files)
        lint_parts.append(ruff_summary)
        if not lint_ok:
            warnings.append(f"Ruff apontou pendências:\n{ruff_summary}")
    if has_js_ts_files:
        eslint_fn = getattr(inspector, "run_eslint", None)
        if callable(eslint_fn):
            es_ok, es_summary = eslint_fn(mission.workspace_path, files)
            lint_parts.append(es_summary)
            if not es_ok:
                warnings.append(f"ESLint apontou pendências:\n{es_summary}")
    lint_summary = " | ".join(p for p in lint_parts if p) or "Lint não aplicável."

    # 4. Suíte de testes por stack (pytest + vitest/jest/npm test)
    test_parts: list[str] = []
    if run_tests:
        if has_py_files or "python" in stacks or not has_js_ts_files:
            tests_ok, py_summary = inspector.run_pytest(mission.workspace_path)
            test_parts.append(f"[pytest] {py_summary}")
            if not tests_ok:
                blocking.append(f"Pytest falhou:\n{py_summary}")
        if has_js_ts_files or "js" in stacks or "ts" in stacks or "react" in stacks:
            js_test_fn = getattr(inspector, "run_js_tests", None)
            if callable(js_test_fn):
                js_t_ok, js_t_summary = js_test_fn(mission.workspace_path)
                test_parts.append(f"[js/ts] {js_t_summary}")
                if not js_t_ok:
                    blocking.append(f"Testes JS/TS falharam:\n{js_t_summary}")
    test_summary = " | ".join(test_parts) if test_parts else "Testes não executados."

    # 5. Verifica se alterações de código de produção (Python ou JS/TS/React) vieram com testes
    code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    prod_code = [f for f in files if Path(f).suffix.lower() in code_exts and not is_test_file_path(f)]
    test_code = [f for f in files if Path(f).suffix.lower() in code_exts and is_test_file_path(f)]
    if prod_code and not test_code:
        warnings.append(
            f"Foram alterados {len(prod_code)} arquivo(s) de código sem criação/atualização de arquivo de teste correspondente."
        )

    if mission.conventions:
        warnings.append(
            "Convenções declaradas para conferência final: " + "; ".join(mission.conventions[:6])
        )

    return AuditReport(
        passed=not blocking,
        files_checked=files,
        blocking_issues=blocking,
        warnings=warnings,
        test_summary=test_summary,
        lint_summary=lint_summary,
    )
