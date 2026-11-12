import importlib.util
import pathlib


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sf = _load("supported_formats")


def test_detects_questions():
    assert sf.asks_about_read_support("voce consegue ler .bat?") is True
    assert sf.asks_about_read_support("quais tipos de arquivo tem suporte nas tools de leitura atuais?") is True
    assert sf.asks_about_read_support("mas q tipo de extensoes o projeto suporta") is True
    assert sf.asks_about_read_support("explica o endpoint de tarefas") is False


def test_facts_mention_bat_and_real_reader():
    assert ".bat" in sf.READ_SUPPORT_FACTS
    assert "pypdf" in sf.READ_SUPPORT_FACTS
    assert "PyMuPDF" not in sf.READ_SUPPORT_FACTS
