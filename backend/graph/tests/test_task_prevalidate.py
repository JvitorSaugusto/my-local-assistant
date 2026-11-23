import pytest
from pydantic import ValidationError

from backend.api.schemas import TaskCreateSchema


def test_prevalidate_rejects_broken_python_in_create_file_and_append():
    with pytest.raises(ValidationError) as exc_create:
        TaskCreateSchema(
            title="quebrado create",
            steps=[
                {
                    "op": "create_file",
                    "path": "app/broken.py",
                    "content": 'x = "linha1\nlinha2"\n',
                }
            ],
        )
    assert "erro de sintaxe Python" in str(exc_create.value)

    with pytest.raises(ValidationError) as exc_append:
        TaskCreateSchema(
            title="quebrado append",
            steps=[
                {
                    "op": "append",
                    "path": "app/utils.py",
                    "content": '\ndef f():\n    return "abc\ndef"\n',
                }
            ],
        )
    assert "erro de sintaxe Python" in str(exc_append.value)


def test_prevalidate_rejects_broken_json_and_unterminated_replace_text():
    with pytest.raises(ValidationError) as exc_json:
        TaskCreateSchema(
            title="json quebrado",
            steps=[{"op": "create_file", "path": "config.json", "content": '{"a": 1, }'}],
        )
    assert "JSON inválido" in str(exc_json.value)

    with pytest.raises(ValidationError) as exc_rep:
        TaskCreateSchema(
            title="replace quebrado",
            steps=[
                {
                    "op": "replace_text",
                    "path": "app/mod.py",
                    "old": "x = 1",
                    "new": 'x = "quebrou\naqui"',
                }
            ],
        )
    assert "string não fechada" in str(exc_rep.value)


def test_prevalidate_accepts_valid_steps():
    task = TaskCreateSchema(
        title="valido",
        steps=[
            {"op": "create_file", "path": "app/ok.py", "content": 'x = "linha1\\nlinha2"\n'},
            {"op": "create_file", "path": "data.json", "content": '{"ok": true}\n'},
            {"op": "replace_text", "path": "app/ok.py", "old": "x = 1", "new": 'x = "a\\nb"'},
        ],
    )
    assert task.title == "valido"
