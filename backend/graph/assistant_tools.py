"""Ferramentas gerais do assistente (fora de arquivos/git): web, data/hora, cálculo e memória do usuário.

Ligadas nos modos Normal, Code e Notas (ver config.py) e registradas no ToolNode (builder.py).
Pesquisa web: WEB_SEARCH_ENABLED=0 desliga; WEB_SEARXNG_URL usa um SearxNG seu em vez do DuckDuckGo.
"""

from __future__ import annotations

from langchain_core.tools import tool

from . import memory, webkit


@tool
def web_search(query: str, max_results: int = 8) -> str:
    """Pesquisa na internet e devolve título, link e trecho dos melhores resultados.

    Use para informação ATUAL ou verificável: notícias, preços, versões e mudanças de bibliotecas, documentação oficial,
    eventos recentes, dados que mudam com o tempo ou que você não sabe com certeza. NÃO use para conceitos estáveis,
    opinião ou conversa. Faça no máximo 3 pesquisas por pergunta e depois abra as melhores páginas com web_fetch.

    Args:
        query: o que pesquisar (frases curtas e específicas funcionam melhor; pode incluir o ano ou a versão).
        max_results: quantos resultados (1 a 10).
    """
    try:
        results, source = webkit.search_web(query, max_results)
    except RuntimeError as exc:
        return f"ERRO na pesquisa: {exc}. Responda com o que você sabe e avise que não conseguiu pesquisar."
    return webkit.format_results(query, results, source)


@tool
def web_fetch(url: str, max_chars: int = 6000) -> str:
    """Abre uma página da web e devolve o texto principal (sem menus e scripts).

    Use depois de web_search para ler a fonte de verdade (documentação, artigo, changelog) antes de afirmar detalhes.
    Só links http/https públicos; PDFs não são lidos.

    Args:
        url: o link completo, copiado dos resultados de web_search ou dado pelo usuário.
        max_chars: tamanho máximo do texto devolvido (500 a 20000).
    """
    return webkit.fetch_page(url, max_chars)


@tool
def current_datetime() -> str:
    """Devolve a data e a hora atuais (com fuso). Use para 'que dia é hoje', prazos, idades, 'faltam quantos dias'."""
    return webkit.now_text()


@tool
def calculate(expression: str) -> str:
    """Calcula uma expressão matemática com exatidão (não faça contas de cabeça).

    Aceita números, + - * / // % ** ( ), pi, e e as funções sqrt, round, min, max, abs, log, log10, log2, exp, sin, cos, tan, floor, ceil.
    Exemplo: '1250 * 1.18 ** 12'. Porcentagem: use 150 * 0.20 para 20% de 150.

    Args:
        expression: a expressão a calcular.
    """
    return webkit.safe_calc(expression)


@tool
def remember_fact(fact: str) -> str:
    """Guarda um fato sobre o usuário para lembrar em conversas futuras.

    Use quando ele pedir 'lembre que...', 'anote que...', 'guarde que...' ou disser uma preferência duradoura
    (sistema operacional, projeto, estilo de resposta). Escreva o fato em uma frase curta, na terceira pessoa.

    Args:
        fact: o fato (ex.: 'Usa Windows 11 e o projeto principal é o inventario-virtual').
    """
    if not memory.enabled():
        return "A memória do assistente está desligada (ASSISTANT_MEMORY=0)."
    return memory.add(fact)[1]


@tool
def list_memories() -> str:
    """Lista os fatos que o usuário pediu para lembrar (com os números para esquecer)."""
    items = memory.list_all()
    return "\n".join(f"[{i['id']}] {i['text']}" for i in items) if items else "Nenhuma memória guardada."


@tool
def forget_fact(fact_id: int) -> str:
    """Apaga uma memória pelo número (veja list_memories). Use quando o usuário pedir para esquecer algo.

    Args:
        fact_id: o número da memória.
    """
    return f"Memória #{fact_id} apagada." if memory.remove(int(fact_id)) else f"Não existe memória #{fact_id}."


WEB_TOOLS = [web_search, web_fetch] if webkit.WEB_ENABLED else []
UTILITY_TOOLS = [current_datetime, calculate]
MEMORY_TOOLS = [remember_fact, list_memories, forget_fact]
ASSISTANT_TOOLS = WEB_TOOLS + UTILITY_TOOLS + MEMORY_TOOLS
