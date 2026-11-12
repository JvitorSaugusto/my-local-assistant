import importlib.util
import pathlib


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hr = _load("heavy_rules")


def test_rules_forbid_pipeline_words_and_invention():
    assert "Nunca cite dossiê" in hr.HEAVY_OUTPUT_RULES
    assert "Não encontrei X" in hr.HEAVY_OUTPUT_RULES
    assert "no máximo 40 itens" in hr.HEAVY_OUTPUT_RULES
