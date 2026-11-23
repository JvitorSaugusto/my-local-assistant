from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from backend.api import live_thoughts
from backend.graph import audit_core as ac
from backend.graph import audit_pdf, ops_core


def test_audit_pdf_contains_all_findings_and_files(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_PACK_DIR", str(tmp_path))
    project = tmp_path / "meu_projeto"
    project.mkdir()
    result = {
        "files": 30,
        "audited_files": [f"app/mod_{i}.py" for i in range(30)],
        "elapsed_seconds": 4.2,
        "tools": {"ruff": "ok", "spacing": "ok"},
        "ignored_false_positives": 1,
        "dropped": [],
        "findings": [
            {
                "id": f"id000{i:04d}",
                "file": f"app/mod_{i % 30}.py",
                "line": 5 + i,
                "end_line": 7 + i,
                "kind": "bug",
                "severity": "high" if i % 2 == 0 else "low",
                "confidence": "high",
                "tool": "ruff",
                "rule": "F821",
                "message": f"Variável não definida ação_{i}",
                "note": "Conferir import",
                "snippet": f"def fn_{i}():\n    return acao_{i}",
            }
            for i in range(35)
        ],
    }

    pdf_path = audit_pdf.build_audit_pdf(str(project), result, scope_label="Projeto completo")
    assert pdf_path.is_file()
    assert pdf_path.suffix == ".pdf"
    raw = pdf_path.read_bytes()
    assert raw.startswith(b"%PDF-1.4")
    assert b"%%EOF" in raw
    assert ops_core.pack_file_path(pdf_path.name) == pdf_path


def test_missing_and_install_tools_respects_allowlist(monkeypatch):
    calls = []
    installed_set = set()

    def fake_tool_cmd(name):
        return [name] if name in installed_set else None

    def fake_run(cmd, cwd, timeout=None):
        calls.append(cmd)
        pkg = cmd[-1]
        if pkg == "radon":
            return SimpleNamespace(returncode=1, stdout="", stderr="falha de rede")
        installed_set.add(pkg)
        return SimpleNamespace(returncode=0, stdout="Successfully installed", stderr="")

    monkeypatch.setattr(ac, "_tool_cmd", fake_tool_cmd)
    monkeypatch.setattr(ac, "_run", fake_run)

    assert ac.missing_tools(("ruff", "radon", "duplication", "spacing")) == ["ruff", "radon"]

    events = []
    outcome = ac.install_tools(["ruff", "radon", "pacote-invalido"], progress_cb=lambda s, d: events.append((s, d)))
    assert outcome["installed"] == ["ruff"]
    assert "radon" in outcome["failed"]
    assert all("pacote-invalido" not in c for c in calls)
    assert events


def test_parse_install_followups_and_pdf_command():
    assert ac.parse_command("@audit pdf") == {"cmd": "pdf"}
    assert ac.parse_command("@audit instalar ruff bandit") == {"cmd": "install", "args": ["ruff", "bandit"]}
    assert ac.parse_command("@audit continuar") == {"cmd": "continue"}

    ask_msg = AIMessage(content="Ferramentas ausentes: ruff. Responda `sim` (ou `@audit instalar`) ou `não` (`@audit continuar`).")
    assert ac.parse_command("sim", [ask_msg, HumanMessage(content="sim")]) == {"cmd": "install", "args": []}
    assert ac.parse_command("pode instalar", [ask_msg, HumanMessage(content="pode instalar")]) == {"cmd": "install", "args": []}
    assert ac.parse_command("não", [ask_msg, HumanMessage(content="não")]) == {"cmd": "continue"}
    assert ac.parse_command("sim", [AIMessage(content="Olá, tudo bem?"), HumanMessage(content="sim")]) is None


def test_live_progress_updates_buffer():
    buf = live_thoughts.live_start("audit-live-test")
    live_thoughts.live_progress("audit-live-test", "Auditoria: ruff", "⏳ ruff: lote 1/3 (40/100 arquivos)")
    snap = live_thoughts.live_snapshot("audit-live-test", after=-1)
    assert snap["changed"] is True
    assert snap["segments"][-1]["label"] == "Auditoria: ruff"
    assert "lote 1/3" in snap["segments"][-1]["text"]
    buf.finish()


def test_run_audit_reports_progress_and_audited_files(tmp_path):
    (tmp_path / "a.py").write_text("class A:\n    pass\nclass B:\n    pass\n", encoding="utf-8")
    seen = []
    res = ac.run_audit(
        str(tmp_path),
        tools=("duplication", "spacing"),
        use_registry=False,
        progress_cb=lambda stage, detail: seen.append((stage, detail)),
    )
    assert res["audited_files"] == ["a.py"]
    assert "elapsed_seconds" in res
    assert any(stage == "spacing" for stage, _ in seen)
