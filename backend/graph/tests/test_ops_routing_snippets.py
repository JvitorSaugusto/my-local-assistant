from types import SimpleNamespace

from backend.graph.ops_core import OPS_NAME, detect_ops_intent


def test_ops_does_not_hijack_multiline_snippet_request_after_ops_reply():
    prev_ops = SimpleNamespace(
        type="ai",
        name=OPS_NAME,
        content="Arquivo gerado. Se quiser mais arquivos ou contexto, me diga.",
    )
    user_prompt = (
        "gemini me mandou isso, retorne todos os trechos\n\n"
        "2. No god-novo (caminhos relativos para sua IA localizar):\n"
        "god-backend/app/ — localizar o endpoint /api/internal/portal/users/sync\n"
        "god-backend/app/ — localizar a rota de login JWT (auth/jwt/ vs /api/auth/jwt/)"
    )
    msgs = [prev_ops, SimpleNamespace(type="human", content=user_prompt)]
    assert detect_ops_intent(user_prompt, msgs) is None


def test_ops_keeps_short_followup_replies_and_explicit_txt():
    prev_ops = SimpleNamespace(
        type="ai",
        name=OPS_NAME,
        content="Quais grupos você quer commitar? Responda com os números ou 'todos'.",
    )
    assert detect_ops_intent("todos", [prev_ops, SimpleNamespace(type="human", content="todos")]) == "todos"
    assert detect_ops_intent("2, 3", [prev_ops, SimpleNamespace(type="human", content="2, 3")]) == "2, 3"

    # Pedir trechos em txt deve ir para CODE (extract_code_snippets), não para Ops (arquivo inteiro)
    assert detect_ops_intent("localize os trechos de auth/jwt e mande em txt", []) is None

    # @txt explícito e pedido de arquivos inteiros em txt continuam indo para Ops
    assert detect_ops_intent("@txt backend/main.py", []) == "txt backend/main.py"
    assert detect_ops_intent("mande os arquivos views.py em txt", []) == "mande os arquivos views.py em txt"


def test_ops_does_not_hijack_return_files_with_search_or_confirm_intent():
    prompt = (
        "me retorne esses arquivos\n\n"
        "No god-backend:\n"
        "O router do sync com o Portal (buscar por users/sync dentro de god-backend/app/routers/ — "
        "provavelmente portal.py ou internal_portal.py) — para confirmar se ele trata cargo=\"Gestor\" "
        "corretamente (sem dar is_superuser=True) e como trata Manutentor.\n"
        "O router de autenticação (buscar por auth/jwt ou jwt dentro de god-backend/app/routers/ e "
        "god-backend/app/main.py) — para confirmar se a rota completa do JWT é /api/auth/jwt/ ou /auth/jwt/."
    )
    assert detect_ops_intent(prompt, []) is None
    assert detect_ops_intent("busque auth/jwt e me mande os arquivos", []) is None
    # Pedidos reais de entrega de arquivos/zip continuam indo para Ops
    assert detect_ops_intent("me mande os arquivos views.py e models.py", []) is not None
    assert detect_ops_intent("compacta a pasta routers em zip", []) is not None
