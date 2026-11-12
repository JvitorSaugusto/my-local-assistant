import importlib.util
import pathlib
import tempfile


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sv = _load("snippet_validator")


def test_valid_block_kept_and_invented_block_removed():
    with tempfile.TemporaryDirectory() as tmp:
        pathlib.Path(tmp, "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        dossier = "\n".join([
            "### 1. Arquivo: `a.py`", "```python", "def f():", "    # ...", "    return 1", "```",
            "### 2. Arquivo: `a.py`", "```python", "def g():", "    pass", "```",
        ])
        out, report = sv.validate_snippets(dossier, tmp)
        assert "def f():" in out and "return 1" in out
        assert "# ..." not in out
        assert "    pass" not in out
        assert "TRECHO NÃO VALIDADO" in out
        assert len(report) == 1


def test_missing_file_block_is_kept():
    with tempfile.TemporaryDirectory() as tmp:
        dossier = "### 1. Arquivo: `novo.py`\n```python\nx = 1\n```"
        out, report = sv.validate_snippets(dossier, tmp)
        assert "x = 1" in out
        assert report == []


def test_no_root_returns_unchanged():
    assert sv.validate_snippets("abc", None) == ("abc", [])
