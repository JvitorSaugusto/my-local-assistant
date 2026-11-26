"""Guardas de confiabilidade máxima: sandbox Git isolado, anti-trapaça em testes e bloqueio de segredos."""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}
PROTECTED_PATH_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
ALLOWED_ENV_FILES = {".env.example", ".env.sample", ".env.template"}

_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:tests?/.*\.py|test_[^/]+\.py|[^/]+_test\.py|"
    r"__tests__/.*\.(?:js|jsx|ts|tsx|mjs|cjs)|"
    r"[^/]+\.(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs))$",
    re.IGNORECASE,
)
_JS_TS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_CONVENTIONAL_TYPES = {
    "feat", "fix", "refactor", "test", "docs", "style", "perf", "chore", "build", "ci",
}
_CONVENTIONAL_HEADER_RE = re.compile(
    r"^(feat|fix|refactor|test|docs|style|perf|chore|build|ci)"
    r"(?:\(([a-zA-Z0-9_./-]+)\))?(!)?:\s*(.+)$",
    re.IGNORECASE,
)
_JS_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/|//[^\n]*")
_JS_TEST_CASE_RE = re.compile(
    r"""\b(?:it|test)(?:\.(?:only|skip|concurrent|each))?\s*\(\s*([`'"])(.*?)\1""",
    re.DOTALL,
)
_JS_ASSERT_RE = re.compile(
    r"\bexpect\s*\(|\bassert(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*\("
)


def is_protected_relative_path(rel_path: str) -> bool:
    """Retorna True se o caminho relativo aponta para área proibida (.git, .env real, traversal)."""
    clean = str(rel_path or "").strip().replace("\\", "/")
    if not clean or clean.startswith("/") or ".." in clean.split("/"):
        return True
    parts = [p for p in clean.split("/") if p]
    for part in parts:
        norm = part.split(":", 1)[0].rstrip(" .").lower()
        if norm in PROTECTED_PATH_PARTS:
            return True
        if (norm == ".env" or norm.startswith(".env.")) and norm not in ALLOWED_ENV_FILES:
            return True
    return False


def is_test_file_path(rel_path: str) -> bool:
    clean = str(rel_path or "").strip().replace("\\", "/")
    return bool(_TEST_FILE_RE.search(clean))


def _collect_test_metrics(source: str) -> tuple[set[str], int] | None:
    """Conta nomes de funções `test_*` e quantidade de `assert`/asserções pytest/unittest."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    test_names: set[str] = set()
    assert_count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            test_names.add(node.name)
        elif isinstance(node, ast.Assert):
            assert_count += 1
        elif isinstance(node, ast.Call):
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else ""
            if attr.startswith("assert") or attr in {"raises", "warns", "approx"}:
                assert_count += 1
    return test_names, assert_count


@dataclass
class TestTamperingReport:
    ok: bool
    violations: list[str] = field(default_factory=list)


def _collect_js_test_metrics(source: str) -> tuple[set[str], int]:
    """Conta casos `test(...)`/`it(...)` e asserções `expect(...)`/`assert(...)` em JS/TS/React."""
    stripped = _JS_COMMENT_RE.sub("", source)
    test_names = {
        re.sub(r"\s+", " ", match.group(2)).strip()
        for match in _JS_TEST_CASE_RE.finditer(stripped)
        if match.group(2).strip()
    }
    assert_count = len(_JS_ASSERT_RE.findall(stripped))
    return test_names, assert_count


def detect_test_tampering(
    before_files: dict[str, str | None],
    after_files: dict[str, str | None],
    *,
    allow_test_deletion: bool = False,
) -> TestTamperingReport:
    """Bloqueia trapaças comuns de LLMs: apagar arquivos de teste, remover casos ou reduzir asserções (Python e JS/TS/React)."""
    if allow_test_deletion:
        return TestTamperingReport(ok=True)

    violations: list[str] = []
    all_paths = sorted(set(before_files) | set(after_files))
    for rel_path in all_paths:
        if not is_test_file_path(rel_path):
            continue
        before = before_files.get(rel_path)
        after = after_files.get(rel_path)
        if before is None:
            continue
        if after is None:
            violations.append(f"Arquivo de teste removido sem autorização: '{rel_path}'.")
            continue

        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            before_metrics = _collect_test_metrics(before)
            after_metrics = _collect_test_metrics(after)
        elif suffix in _JS_TS_EXTS:
            before_metrics = _collect_js_test_metrics(before)
            after_metrics = _collect_js_test_metrics(after)
        else:
            continue

        if before_metrics is None or after_metrics is None:
            continue
        before_tests, before_asserts = before_metrics
        after_tests, after_asserts = after_metrics

        removed_tests = sorted(before_tests - after_tests)
        if removed_tests:
            violations.append(
                f"Teste(s) removido(s) em '{rel_path}': {', '.join(removed_tests)}."
            )
        if before_asserts > 0 and after_asserts < before_asserts:
            violations.append(
                f"Número de asserções diminuiu em '{rel_path}' ({before_asserts} -> {after_asserts})."
            )

    return TestTamperingReport(ok=not violations, violations=violations)


def _infer_conventional_type(title: str, changed_files: list[str] | None = None) -> str:
    low = str(title or "").lower()
    if re.search(r"\b(?:corrig|fix|bug|erro|falha|repar|blind|quebr|resolv)\w*", low):
        return "fix"
    if re.search(r"\b(?:test|pytest|vitest|jest|spec|cobertura)\w*", low):
        return "test"
    if re.search(r"\b(?:refator|refactor|padroniz|limp|renome|organiz|reestrutur)\w*", low):
        return "refactor"
    if re.search(r"\b(?:doc|readme|documenta|coment)\w*", low):
        return "docs"
    if re.search(r"\b(?:perf|otimiz|vram|cache|veloz|lat[eê]ncia)\w*", low):
        return "perf"
    if re.search(r"\b(?:estilo|style|css|layout|[ií]cone|svg|tema|visual)\w*", low):
        return "style"
    if re.search(r"\b(?:chore|config|depend[eê]ncia|package\.json|build|ci|workflow)\b", low):
        return "chore"

    files = [str(f).replace("\\", "/") for f in (changed_files or []) if str(f).strip()]
    if files:
        if all(is_test_file_path(f) for f in files):
            return "test"
        if all(Path(f).suffix.lower() in {".md", ".txt", ".rst"} for f in files):
            return "docs"
        if all(Path(f).suffix.lower() in {".css", ".scss", ".sass", ".less"} for f in files):
            return "style"
    return "feat"


def _infer_conventional_scope(changed_files: list[str] | None = None, explicit_scope: str | None = None) -> str:
    if explicit_scope and str(explicit_scope).strip():
        clean = re.sub(r"[^a-z0-9_-]+", "-", str(explicit_scope).lower()).strip("-")
        if clean:
            return clean[:24]

    generic = {"src", "app", "backend", "frontend", "web", "client", "server", "lib", "packages", "tests", "__tests__"}
    candidates: list[str] = []
    for raw in changed_files or []:
        parts = [p for p in str(raw).replace("\\", "/").split("/") if p]
        dirs = parts[:-1]
        picked = next((d for d in reversed(dirs) if d.lower() not in generic), "")
        if not picked and parts:
            picked = Path(parts[-1]).stem
        norm = re.sub(r"[^a-z0-9_-]+", "-", picked.lower()).strip("-")
        if norm:
            candidates.append(norm[:24])

    if not candidates:
        return ""
    if len(set(candidates)) == 1:
        return candidates[0]
    # Escopo mais frequente entre os arquivos alterados
    return max(set(candidates), key=candidates.count)


def format_conventional_commit(
    title: str,
    *,
    changed_files: list[str] | None = None,
    commit_type: str | None = None,
    commit_scope: str | None = None,
) -> str:
    """Formata a mensagem de commit estritamente no padrão Conventional Commits (<= 72 chars)."""
    raw = re.sub(r"\s+", " ", str(title or "")).strip().rstrip(".")
    match = _CONVENTIONAL_HEADER_RE.match(raw)
    if match:
        ctype = match.group(1).lower()
        cscope = (match.group(2) or "").strip().lower()
        bang = match.group(3) or ""
        desc = match.group(4).strip()
        if not cscope and commit_scope:
            cscope = _infer_conventional_scope(changed_files, commit_scope)
        prefix = f"{ctype}({cscope}){bang}: " if cscope else f"{ctype}{bang}: "
        max_desc = max(12, 72 - len(prefix))
        return prefix + desc[:max_desc].rstrip()

    ctype = (commit_type or "").strip().lower()
    if ctype not in _CONVENTIONAL_TYPES:
        ctype = _infer_conventional_type(raw, changed_files)
    cscope = _infer_conventional_scope(changed_files, commit_scope)
    desc = raw or "atualiza arquivos da tarefa"
    if len(desc) >= 2 and desc[0].isupper() and desc[1].islower():
        desc = desc[0].lower() + desc[1:]
    prefix = f"{ctype}({cscope}): " if cscope else f"{ctype}: "
    max_desc = max(12, 72 - len(prefix))
    return prefix + desc[:max_desc].rstrip()


def slugify_branch_part(text: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (slug[:max_len].strip("-")) or "mission"


class GitSandboxError(RuntimeError):
    """Erro operacional no sandbox Git da missão."""


class GitMissionSandbox:
    """Isola toda execução autônoma em uma branch dedicada com checkpoints e rollback cirúrgico."""

    def __init__(self, workspace_path: str | Path) -> None:
        self.repo = Path(workspace_path).expanduser().resolve()
        if not self.repo.is_dir():
            raise GitSandboxError(f"Workspace não existe: {self.repo}")
        if not (self.repo / ".git").exists():
            raise GitSandboxError(f"Workspace não é um repositório Git: {self.repo}")

    def _run_git(self, *args: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        res = subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if check and res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip()
            raise GitSandboxError(f"git {' '.join(args)} falhou: {detail}")
        return res

    def current_branch(self) -> str:
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def head_commit(self) -> str:
        return self._run_git("rev-parse", "HEAD").stdout.strip()

    def is_clean(self) -> bool:
        out = self._run_git("status", "--porcelain", "-uall").stdout.strip()
        return out == ""

    def has_commits(self) -> bool:
        return self._run_git("rev-parse", "--verify", "HEAD", check=False).returncode == 0

    def ensure_mission_branch(
        self,
        mission_id: str,
        title: str,
        prefix: str = "auto",
        *,
        require_clean_for_new: bool = True,
    ) -> tuple[str, str]:
        """Garante branch dedicada `auto/<slug>-<id>` (nunca opera em main/master e protege worktree suja)."""
        if not self.has_commits():
            raise GitSandboxError(
                "O repositório Git ainda não possui nenhum commit inicial. "
                "Faça pelo menos um commit inicial antes de executar o Modo Autônomo."
            )

        safe_prefix = slugify_branch_part(prefix, max_len=16) or "auto"
        slug = slugify_branch_part(title, max_len=28)
        short_id = slugify_branch_part(mission_id, max_len=12)
        branch = f"{safe_prefix}/{slug}-{short_id}"

        current = self.current_branch()
        if current == branch:
            return branch, self.head_commit()

        exists = self._run_git("rev-parse", "--verify", f"refs/heads/{branch}", check=False).returncode == 0
        if require_clean_for_new and not self.is_clean():
            dirty = self.changed_files()
            sample = ", ".join(dirty[:5]) + ("..." if len(dirty) > 5 else "")
            raise GitSandboxError(
                f"Workspace com alterações não commitadas ({sample}). "
                "Faça commit ou stash antes de iniciar/trocar para a branch da missão, "
                "evitando misturar ou perder trabalho local no rollback."
            )

        if exists:
            self._run_git("checkout", branch)
        else:
            self._run_git("checkout", "-b", branch)

        if self.current_branch() in PROTECTED_BRANCHES:
            raise GitSandboxError("Bloqueio de segurança: operação recusada em branch protegida.")
        return branch, self.head_commit()

    def changed_files(self) -> list[str]:
        out = self._run_git("status", "--porcelain", "-uall").stdout.splitlines()
        files: list[str] = []
        for line in out:
            if len(line) < 4:
                continue
            raw_path = line[3:].strip()
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ", 1)[1].strip()
            raw_path = raw_path.strip('"').replace("\\", "/")
            if raw_path:
                files.append(raw_path)
        return sorted(dict.fromkeys(files))

    def snapshot_files_at_head(self, rel_paths: list[str]) -> dict[str, str | None]:
        snap: dict[str, str | None] = {}
        for rel in rel_paths:
            res = self._run_git("show", f"HEAD:{rel}", check=False)
            snap[rel] = res.stdout if res.returncode == 0 else None
        return snap

    def snapshot_working_files(self, rel_paths: list[str]) -> dict[str, str | None]:
        snap: dict[str, str | None] = {}
        for rel in rel_paths:
            full = (self.repo / rel).resolve()
            try:
                full.relative_to(self.repo)
            except ValueError:
                snap[rel] = None
                continue
            if full.is_file():
                snap[rel] = full.read_text(encoding="utf-8", errors="replace")
            else:
                snap[rel] = None
        return snap

    def commit_item(
        self,
        item_id: str,
        title: str,
        *,
        allow_test_deletion: bool = False,
        commit_type: str | None = None,
        commit_scope: str | None = None,
    ) -> str | None:
        """Valida segurança + anti-trapaça e cria um commit atômico em Conventional Commits."""
        branch = self.current_branch()
        if branch in PROTECTED_BRANCHES:
            raise GitSandboxError(f"Commit bloqueado na branch protegida '{branch}'.")

        changed = self.validate_working_changes(allow_test_deletion=allow_test_deletion)
        if not changed:
            return None

        self._run_git("add", "--", *changed)
        subject = format_conventional_commit(
            title,
            changed_files=changed,
            commit_type=commit_type,
            commit_scope=commit_scope,
        )
        trailer = f"Autonomous-Item: {item_id}" if item_id else ""
        if trailer:
            self._run_git("commit", "-m", subject, "-m", trailer)
        else:
            self._run_git("commit", "-m", subject)
        return self.head_commit()

    def rollback_working_tree(self) -> None:
        """Desfaz alterações não commitadas e remove arquivos untracked gerados pelo item falho."""
        branch = self.current_branch()
        if branch in PROTECTED_BRANCHES:
            raise GitSandboxError(f"Rollback recusado na branch protegida '{branch}'.")
        self._run_git("reset", "--hard", "HEAD")
        self._run_git("clean", "-fd")

    def validate_working_changes(self, *, allow_test_deletion: bool = False) -> list[str]:
        """Valida arquivos modificados sem commitar (proteção de segredos + anti-trapaça em testes)."""
        changed = self.changed_files()
        if not changed:
            return []
        forbidden = [p for p in changed if is_protected_relative_path(p)]
        if forbidden:
            raise GitSandboxError(
                f"Arquivos protegidos não podem ser alterados pela missão: {', '.join(forbidden)}"
            )
        before = self.snapshot_files_at_head(changed)
        after = self.snapshot_working_files(changed)
        tamper = detect_test_tampering(before, after, allow_test_deletion=allow_test_deletion)
        if not tamper.ok:
            raise GitSandboxError("Bloqueio anti-trapaça em testes: " + " | ".join(tamper.violations))
        return changed

    def recent_commits(self, base_commit: str | None = None, limit: int = 25) -> list[dict[str, str]]:
        """Lista commits gerados na branch desde `base_commit`."""
        rev_range = f"{base_commit}..HEAD" if base_commit else "HEAD"
        res = self._run_git(
            "log",
            f"-n{max(1, min(limit, 100))}",
            "--pretty=format:%H%x1f%s%x1f%cI",
            rev_range,
            check=False,
        )
        if res.returncode != 0:
            return []
        commits: list[dict[str, str]] = []
        for line in res.stdout.splitlines():
            parts = line.split("")
            if len(parts) == 3:
                commits.append({"sha": parts[0], "subject": parts[1], "date": parts[2]})
        return commits

    def diff_from_base(self, base_commit: str, max_chars: int = 24000) -> str:
        """Retorna `--stat` + diff acumulado desde o commit base (incluindo alterações pendentes se auto_commit=False)."""
        stat = self._run_git("diff", "--stat", base_commit, check=False).stdout.strip()
        diff = self._run_git("diff", base_commit).stdout
        combined = f"=== RESUMO DO DIFF ===\n{stat}\n\n=== DIFF ===\n{diff}" if stat else diff
        if len(combined) > max_chars:
            return combined[:max_chars] + "\n\n[... diff truncado para revisão ...]"
        return combined
