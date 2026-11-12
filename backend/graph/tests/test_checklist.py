import importlib.util
import pathlib


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ck = _load("checklist")

MSG = (
    "backend/static/script.js: a função que renderiza a lista, o handler do X e o handler de colar na fila rápida.\n"
    "backend/rag/api.py: os endpoints DELETE /sources/{id} e PUT /links.\n"
    "backend/api/controllers/tasks_controller.py: o POST /{thread_id} e o bulk."
)


def test_extract_checklist_one_item_per_file():
    items = ck.extract_checklist(MSG)
    assert [item["file"] for item in items] == [
        "backend/static/script.js",
        "backend/rag/api.py",
        "backend/api/controllers/tasks_controller.py",
    ]
    assert "handler do X" in items[0]["what"]


def test_render_checklist_lists_files():
    text = ck.render_checklist(ck.extract_checklist(MSG))
    assert "1. backend/static/script.js" in text
    assert "3. backend/api/controllers/tasks_controller.py" in text


def test_part_is_none_without_files():
    assert ck.gatherer_coverage_part("me explica como funciona o grafo") is None


def test_part_has_rules_and_checklist():
    part = ck.gatherer_coverage_part(MSG)
    assert "COBERTURA DO PEDIDO" in part
    assert "CHECKLIST DO PEDIDO" in part
