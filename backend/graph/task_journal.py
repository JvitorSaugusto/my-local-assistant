"""Diário de alterações das tasks em modo dinâmico (LLM edita sozinho).

Antes de cada gravação das tools, o conteúdo original do arquivo é guardado. Com isso:
- se a task falha (verificação, erro, nenhuma alteração), as edições DESTA execução são desfeitas sozinhas;
- o "Ver alterações" mostra o que a task realmente mudou (e não o git diff, que mistura outras mudanças);
- "Reprovar" pode desfazer tudo no disco, sem `git checkout` (que apagaria alterações suas ainda não commitadas).

Tudo em disco, fora do projeto: ~/.assistente_local/task_journal/task_<id> (ou TASK_JOURNAL_DIR).
Variáveis opcionais: TASK_ROLLBACK_ON_FAIL=0 desliga o desfazer automático em falha.
O diário é "melhor esforço": qualquer erro aqui é ignorado e nunca derruba a task.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

_ACTIVE = {}
_KEEP_SECONDS = 14 * 24 * 3600
_MAX_DIFF_CHARS = 40_000


def _base_dir():
    raw = os.getenv("TASK_JOURNAL_DIR")
    base = Path(raw) if raw else Path.home() / ".assistente_local" / "task_journal"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sha(data):
    return None if data is None else hashlib.sha1(data).hexdigest()


def _read_current(target):
    try:
        return target.read_bytes() if target.is_file() else None
    except OSError:
        return None


def _text(data):
    if data is None:
        return ""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _unified(rel, before, after):
    return "".join(
        difflib.unified_diff(
            _text(before).splitlines(keepends=True),
            _text(after).splitlines(keepends=True),
            fromfile="a/" + rel,
            tofile="b/" + rel,
            n=3,
        )
    )


class TaskJournal:
    def __init__(self, workspace, task_id, directory):
        self.root = Path(workspace).resolve()
        self.task_id = int(task_id)
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.json"
        self.data = self._load()
        self.run_orig = {}   # estado no início desta execução (em memória): base do desfazer automático
        self.run_new = set()  # arquivos que entraram no diário nesta execução

    def _load(self):
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"task_id": self.task_id, "workspace": str(self.root), "files": {}}

    def _save(self):
        self.manifest_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _original_bytes(self, info):
        if not info.get("existed"):
            return None
        return (self.dir / info["blob"]).read_bytes()

    def record(self, path):
        """Chamado ANTES de gravar `path`."""
        target = Path(path).resolve()
        try:
            rel = target.relative_to(self.root).as_posix()
        except ValueError:
            return
        current = _read_current(target)
        if rel not in self.run_orig:
            self.run_orig[rel] = current
        files = self.data["files"]
        if rel in files:
            return
        blob = None
        if current is not None:
            blob = "%04d.orig" % (len(files) + 1)
            (self.dir / blob).write_bytes(current)
        files[rel] = {"existed": current is not None, "blob": blob, "after": None}
        self.run_new.add(rel)
        self._save()

    def finish(self):
        for rel, info in self.data["files"].items():
            info["after"] = _sha(_read_current(self.root / rel))
        self._save()

    def diff(self):
        parts, new_files, truncated = [], [], False
        for rel, info in self.data["files"].items():
            current = _read_current(self.root / rel)
            before = self._original_bytes(info)
            if before is None and current is not None:
                new_files.append({"path": rel, "content": _text(current)[:_MAX_DIFF_CHARS]})
            elif before != current:
                parts.append(_unified(rel, before, current) or ("(arquivo %s removido ou binário)\n" % rel))
        text = "".join(parts)
        if len(text) > _MAX_DIFF_CHARS:
            text, truncated = text[:_MAX_DIFF_CHARS] + "\n[... diff truncado ...]", True
        return {
            "base": "alterações desta task (antes -> depois)",
            "diff": text,
            "new_files": new_files,
            "missing": [],
            "truncated": truncated,
        }

    def _put_back(self, target, original):
        if original is None:
            if target.is_file():
                target.unlink()
                return True
            return False
        if _read_current(target) != original:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)
            return True
        return False

    def rollback_run(self):
        """Desfaz só as edições desta execução (usado quando a task falha). Guarda o diff da tentativa."""
        if not self.run_orig:
            return []
        attempt = []
        for rel, original in self.run_orig.items():
            current = _read_current(self.root / rel)
            if original is None and current is not None:
                attempt.append("--- arquivo novo: %s\n%s\n" % (rel, _text(current)[:5000]))
            elif original != current:
                attempt.append(_unified(rel, original, current))
        text = "".join(attempt)[:_MAX_DIFF_CHARS]
        restored = []
        for rel, original in self.run_orig.items():
            try:
                if self._put_back(self.root / rel, original):
                    restored.append(rel)
            except OSError:
                continue
        for rel in self.run_new:
            info = self.data["files"].pop(rel, None)
            if info and info.get("blob"):
                (self.dir / info["blob"]).unlink(missing_ok=True)
        self.run_orig, self.run_new = {}, set()
        if restored and text:
            (self.dir / "failed_attempt.diff").write_text(text, encoding="utf-8")
        self._save()
        return restored

    def revert_all(self):
        """Volta os arquivos ao estado de ANTES da task. Não mexe no que mudou depois (devolve como conflito)."""
        restored, conflicts = [], []
        for rel, info in self.data["files"].items():
            target = self.root / rel
            if info.get("after") is not None and _sha(_read_current(target)) != info["after"]:
                conflicts.append(rel)
                continue
            try:
                if self._put_back(target, self._original_bytes(info)):
                    restored.append(rel)
            except OSError:
                conflicts.append(rel)
        return restored, conflicts


def _journal_dir(task_id):
    return _base_dir() / ("task_%d" % int(task_id))


def _cleanup_old(base):
    now = time.time()
    for item in base.glob("task_*"):
        try:
            if now - item.stat().st_mtime > _KEEP_SECONDS:
                shutil.rmtree(item, ignore_errors=True)
        except OSError:
            continue


def begin_journal(workspace, task_id):
    """Liga o diário para esta execução da task. Devolve o diário (ou None se não foi possível)."""
    try:
        if not workspace:
            return None
        base = _base_dir()
        _cleanup_old(base)
        journal = TaskJournal(workspace, task_id, _journal_dir(task_id))
        _ACTIVE[str(Path(workspace).resolve())] = journal
        return journal
    except Exception:  # noqa: BLE001 - o diário nunca derruba a task
        return None


def record_write(path):
    """Chamado pelas tools antes de gravar um arquivo. Sem diário ativo, não faz nada."""
    if not _ACTIVE:
        return
    try:
        resolved = Path(path).resolve()
        for journal in list(_ACTIVE.values()):
            try:
                resolved.relative_to(journal.root)
            except ValueError:
                continue
            journal.record(resolved)
    except Exception:  # noqa: BLE001
        return


def journal_end(workspace):
    try:
        journal = _ACTIVE.pop(str(Path(workspace).resolve()), None) if workspace else None
        if journal is not None:
            journal.finish()
    except Exception:  # noqa: BLE001
        return


def journal_rollback(workspace, task_id):
    """Task falhou: desfaz as edições desta execução. Devolve a lista de arquivos restaurados."""
    if os.getenv("TASK_ROLLBACK_ON_FAIL", "1") != "1" or not workspace:
        return []
    try:
        journal = _ACTIVE.get(str(Path(workspace).resolve()))
        if journal is None or journal.task_id != int(task_id):
            return []
        return journal.rollback_run()
    except Exception:  # noqa: BLE001
        return []


def _load_for(workspace, task_id):
    directory = _journal_dir(task_id)
    if not (directory / "manifest.json").is_file() and not (directory / "failed_attempt.diff").is_file():
        return None, directory
    journal = TaskJournal(workspace, task_id, directory)
    if str(Path(journal.data.get("workspace", workspace)).resolve()) != str(Path(workspace).resolve()):
        return None, directory
    return journal, directory


def journal_diff(workspace, task_id):
    """Diff real da task (no formato de /diff) ou None se não há diário."""
    try:
        journal, directory = _load_for(workspace, task_id)
        if journal is None:
            return None
        if journal.data["files"]:
            return journal.diff()
        failed = directory / "failed_attempt.diff"
        if failed.is_file():
            return {
                "base": "tentativa que FALHOU (já desfeita automaticamente)",
                "diff": failed.read_text(encoding="utf-8"),
                "new_files": [],
                "missing": [],
                "truncated": False,
            }
        return None
    except Exception:  # noqa: BLE001
        return None


def journal_revert(workspace, task_id):
    """Desfaz no disco tudo o que a task fez. None se não há diário."""
    try:
        journal, directory = _load_for(workspace, task_id)
        if journal is None or not journal.data["files"]:
            return None
        restored, conflicts = journal.revert_all()
        if not conflicts:
            shutil.rmtree(directory, ignore_errors=True)
        return {"restored": restored, "conflicts": conflicts}
    except Exception:  # noqa: BLE001
        return None


def discard_journal(task_id):
    try:
        shutil.rmtree(_journal_dir(task_id), ignore_errors=True)
    except Exception:  # noqa: BLE001
        return


def syntax_problems_for_paths(workspace, paths):
    """Sintaxe de .json (e .js, se o task_guards existir) dos arquivos gravados pela task."""
    problems = []
    root = Path(workspace or ".").resolve()
    for rel in paths or []:
        target = (root / str(rel)).resolve()
        if str(rel).lower().endswith(".json") and target.is_file():
            try:
                json.loads(target.read_text(encoding="utf-8-sig"))
            except ValueError as exc:
                problems.append("%s: JSON inválido (%s)" % (rel, exc))
            except OSError:
                pass
    js = [p for p in paths or [] if str(p).lower().endswith((".js", ".mjs", ".cjs"))]
    if js:
        try:
            from types import SimpleNamespace

            from .task_guards import extra_syntax_problems
        except ImportError:
            return problems
        problems.extend(extra_syntax_problems(workspace, [SimpleNamespace(path=p) for p in js]))
    return problems


def journal_originals(task_id):
    """Estado ANTERIOR à task de cada arquivo que ela mexeu: {"workspace", "files": {rel: bytes|None}} ou None."""
    try:
        directory = _journal_dir(task_id)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        files = {}
        for rel, info in manifest.get("files", {}).items():
            files[rel] = (directory / info["blob"]).read_bytes() if info.get("existed") else None
        if not files:
            return None
        return {"workspace": manifest["workspace"], "files": files}
    except Exception:  # noqa: BLE001
        return None
