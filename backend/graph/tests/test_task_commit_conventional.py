"""Testes de Conventional Commits e captura de delete/move no commit automático das tasks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from backend.graph import task_commit
from backend.graph.task_commit import capture_originals, commit_task, format_conventional_commit


def test_format_conventional_commit_standardizes_headers_aliases_and_scopes():
    # Já em Conventional Commits -> preserva tipo, escopo e descrição
    assert (
        format_conventional_commit(
            "fix(router): rotear perguntas técnicas para CODE",
            ["backend/graph/nodes.py"],
        )
        == "fix(router): rotear perguntas técnicas para CODE"
    )

    # Alias "tests" -> normalizado para "test"
    assert (
        format_conventional_commit(
            "tests(extractor): cobrir fronteira de token",
            ["backend/graph/tests/test_code_extractor.py"],
        )
        == "test(extractor): cobrir fronteira de token"
    )

    # Prefixo não convencional ("frontend: ...") vira escopo com tipo inferido
    assert (
        format_conventional_commit(
            "frontend: subir conversa para o topo da sidebar",
            ["backend/static/script.js"],
        )
        == "feat(frontend): subir conversa para o topo da sidebar"
    )

    # Título livre com verbo de correção -> infere fix + escopo pelo diretório
    msg = format_conventional_commit(
        "Corrigir erro de permissão ao buscar pasta",
        ["backend/graph/tools.py"],
    )
    assert msg == "fix(graph): corrigir erro de permissão ao buscar pasta"

    # Nunca ultrapassa 72 caracteres na primeira linha
    long_msg = format_conventional_commit(
        "feat(autonomous): " + "a" * 120,
        ["backend/autonomous/runner.py"],
    )
    assert len(long_msg) <= 72


def test_capture_originals_tracks_delete_and_move_steps(tmp_path):
    (tmp_path / "old.py").write_bytes(b"x = 1\n")
    (tmp_path / "remove_me.py").write_bytes(b"y = 2\n")

    pre = capture_originals(
        str(tmp_path),
        [
            {"op": "delete_file", "path": "remove_me.py"},
            {"op": "move_file", "source": "old.py", "destination": "new.py"},
        ],
    )
    assert pre["multi"] is False
    assert pre["files"]["remove_me.py"] == b"y = 2\n"
    assert pre["files"]["old.py"] == b"x = 1\n"
    assert pre["files"]["new.py"] is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_commit_task_writes_conventional_commit_with_task_id_trailer(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "feat/test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@local"], cwd=str(repo), check=True, capture_output=True)
    (repo / "app").mkdir()
    (repo / "app" / "routes.py").write_bytes(b"a = 1\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=str(repo), check=True, capture_output=True)

    monkeypatch.setenv("TASK_AUTOCOMMIT", "1")
    monkeypatch.setattr(task_commit, "_RUNTIME_ENABLED", True)

    steps = [{"op": "replace_text", "path": "app/routes.py", "old": "a = 1", "new": "a = 2"}]
    pre = capture_originals(str(repo), steps)
    (repo / "app" / "routes.py").write_bytes(b"a = 2\n")

    summary = commit_task(str(repo), 42, "Corrigir retorno da rota", pre)
    assert summary is not None
    assert "fix(routes): corrigir retorno da rota" in summary
    assert "task #42" in summary

    full_msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert full_msg.splitlines()[0] == "fix(routes): corrigir retorno da rota"
    assert "Task-ID: #42" in full_msg
