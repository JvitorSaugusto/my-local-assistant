from backend.graph.nodes import _should_force_code_route

WS = "C:/workspace/god-novo"


def test_force_code_route_detects_project_and_code_queries():
    cases = [
        "confirma no god-backend se o sync com o Portal define is_superuser para Gestor e Manutentor",
        "verifica o router de sync com o Portal e o router de autenticação JWT",
        "qual a rota de login JWT? /auth/jwt/ ou /api/auth/jwt/?",
        "qual o prefixo da rota de login jwt?",
        "como está o sync de usuários no backend?",
        "me mostra onde fica o seed do usuário esolvere no banco",
        "por que está dando erro 422 no endpoint de usuários?",
        "olhe em proxy_api/core/services.py como funciona _resolve_god_origin_and_cargo",
        "no projeto atual, onde está definido DEFAULT_PRESETS?",
        "como funciona o portal_internal.py?",
        "retorne todos os trechos sobre auth/jwt",
    ]
    for msg in cases:
        assert _should_force_code_route(msg, WS) is not None, f"Deveria rotear para CODE: {msg}"


def test_force_code_route_preserves_normal_chat_and_notes():
    cases = [
        "oi, tudo bem?",
        "qual a capital da França?",
        "você prefere café/leite ou chá?",
        "qual a diferença entre trabalho/estudo em 2026/2027?",
        "crie uma nota sobre FastAPI e JWT",
        "@nota explicar routers do FastAPI",
        "@normal explica isso sem ler arquivos",
        "leia este link https://docs.python.org/3/library/re.html e resuma",
        "o que é um banco de dados relacional?",
    ]
    for msg in cases:
        assert _should_force_code_route(msg, WS) is None, f"Não deveria forçar CODE: {msg}"

    # Sem workspace aberto, nunca força CODE
    assert _should_force_code_route("verifica o router portal_internal.py", "") is None
    assert _should_force_code_route("verifica o router portal_internal.py", None) is None
