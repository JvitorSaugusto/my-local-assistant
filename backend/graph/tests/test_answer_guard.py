import importlib.util
import pathlib


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ag = _load("answer_guard")


def test_scrub_removes_dossie():
    out = ag.scrub_meta_references("O dossiê não contém nenhum arquivo .bat")
    assert "dossi" not in out.lower()
    assert out.startswith("Não encontrei")


def test_scrub_keeps_code_blocks():
    text = "Veja:\n```python\nprint('tool calls')\n```\nSegundo o dossiê, ok."
    out = ag.scrub_meta_references(text)
    assert "print('tool calls')" in out
    assert "dossi" not in out.lower()


def test_detect_repetition_extension_loop():
    letters = "abcdefghijklmnopqrstuvwxyz"
    text = " ".join(".x%s%s," % (a, b) for a in letters for b in letters)
    assert ag.detect_repetition(text) is True


def test_detect_repetition_normal_text():
    assert ag.detect_repetition("A função chat_with_ai inicia o grafo e devolve a resposta ao frontend.") is False


def test_ground_answer_flags_invented_name():
    corpus = "function toggleSourceLink() openSourcesMenu /api/rag/links backend/static/script.js"
    answer = "Veja `toggleSourceLink()` e `_pasteToQueue` em `backend/static/script.js` e `/api/rag/links`."
    text, invalid = ag.ground_answer(answer, corpus)
    assert invalid == ["_pasteToQueue"]
    assert "`_pasteToQueue` (não confirmado no código)" in text
    assert "`toggleSourceLink()`" in text


def test_route_with_router_prefix_is_not_flagged():
    corpus = '@rag_router.put("/links")'
    text, invalid = ag.ground_answer("Use `/api/rag/links`.", corpus)
    assert invalid == []


def test_missing_route_and_file_flagged():
    text, invalid = ag.ground_answer("Use `/api/nao/existe` e `foo/bar.py`.", "nada aqui")
    assert "/api/nao/existe" in invalid
    assert "foo/bar.py" in invalid


def test_names_not_checked_without_dossier():
    text, invalid = ag.ground_answer("Use `minha_funcao_x`.", "", check_names=False)
    assert invalid == []


def test_finalize_answer():
    result = ag.finalize_answer("Segundo o dossiê, use `minhaFuncao_x`.", "texto sem a funcao")
    assert "dossi" not in result["text"].lower()
    assert result["invalid"] == ["minhaFuncao_x"]
    assert result["degenerate"] is False


def test_wants_raw_output():
    assert ag.wants_raw_output("me dá o retorno bruto do generate_repo_map") is True
    assert ag.wants_raw_output("explique o fluxo") is False
