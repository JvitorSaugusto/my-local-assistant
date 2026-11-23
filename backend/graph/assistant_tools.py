"""Ferramentas gerais do assistente (fora de arquivos/git): web, data/hora, cálculo e memória do usuário.

Ligadas nos modos Normal, Code e Notas (ver config.py) e registradas no ToolNode (builder.py).
Pesquisa web: WEB_SEARCH_ENABLED=0 desliga; WEB_SEARXNG_URL usa um SearxNG seu em vez do DuckDuckGo.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from backend.api.uploads import find_upload, list_uploads

from . import memory, webkit
from .file_readers import read_text_for_tools


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
    if not webkit.web_enabled():
        return "A pesquisa na web está desligada nas Configurações. Responda com o seu conhecimento local e avise o usuário se precisar de dados atuais."
    try:
        results, source = webkit.search_web(query, max_results)
    except RuntimeError as exc:
        return f"ERRO na pesquisa: {exc}. Responda com o que você sabe e avise que não conseguiu pesquisar."
    return webkit.format_results(query, results, source)


@tool
def web_fetch(url: str, max_chars: int = 6000) -> str:
    """Abre uma página da web e devolve o texto principal (sem menus e scripts).

    Use depois de web_search para ler a fonte de verdade (documentação, artigo, changelog) antes de afirmar detalhes.
    Suporta páginas HTML, PDFs públicos online e links de vídeos do YouTube (puxa a transcrição).

    Args:
        url: o link completo, copiado dos resultados de web_search ou dado pelo usuário.
        max_chars: tamanho máximo do texto devolvido (500 a 20000).
    """
    if not webkit.web_enabled():
        return "A pesquisa/leitura na web está desligada nas Configurações."
    return webkit.fetch_page(url, max_chars)


@tool
def youtube_transcript(url: str, max_chars: int = 12000) -> str:
    """Obtém título, canal e transcrição (legendas) de um vídeo do YouTube para resumir ou estudar.

    Args:
        url: link do YouTube (youtube.com/watch?v=..., youtu.be/..., shorts, live).
        max_chars: limite de caracteres da transcrição (500 a 25000).
    """
    if not webkit.web_enabled():
        return "A pesquisa/leitura na web está desligada nas Configurações."
    return webkit.fetch_youtube_transcript(url, max_chars)


@tool
def current_datetime() -> str:
    """Devolve a data e a hora atuais (com fuso). Use para 'que dia é hoje', prazos, idades, 'faltam quantos dias'."""
    return webkit.now_text()


@tool
def read_attachment(source: str, config: RunnableConfig, offset: int = 0, max_chars: int = 12000) -> str:
    """Lê o texto de um arquivo anexado nesta conversa (PDF, DOCX, TXT, MD, CSV, JSON, PY), mesmo sem projeto/workspace.

    Use sempre que a mensagem trouxer `[Arquivos anexados]` com caminhos `@global/...` ou nomes de arquivos anexados.

    Args:
        source: caminho (`@global/...`) ou nome do arquivo anexado (ex.: `contrato.pdf`).
        offset: caractere inicial para ler continuações de arquivos grandes (padrão 0).
        max_chars: limite de caracteres retornados por chamada (500 a 25000).
    """
    thread_id = str(((config or {}).get("configurable") or {}).get("thread_id") or "").strip() or None
    path, error = find_upload("", thread_id, source)
    if error or path is None:
        return error or f"ERRO: anexo '{source}' não encontrado."
    try:
        text = read_text_for_tools(path)
    except Exception as exc:  # noqa: BLE001
        return f"ERRO ao ler anexo '{path.name}': {exc}"
    start = max(0, int(offset or 0))
    limit = max(500, min(int(max_chars or 12000), 25000))
    chunk = text[start : start + limit]
    total = len(text)
    if start + limit < total:
        chunk += f"\n\n[... mostrando caracteres {start}-{start + limit} de {total}; chame read_attachment(source='{path.name}', offset={start + limit}) para continuar]"
    return f"Arquivo anexado: {path.name} ({total} caracteres)\n\n{chunk}"


@tool
def list_chat_attachments(config: RunnableConfig) -> str:
    """Lista os arquivos globais anexados nesta conversa."""
    thread_id = str(((config or {}).get("configurable") or {}).get("thread_id") or "").strip()
    if not thread_id:
        return "Nenhuma conversa associada."
    items = list_uploads("", thread_id)
    if not items:
        return "Nenhum anexo global nesta conversa."
    return "\n".join(f"- {i['name']} ({i['size']} bytes) -> {i['path']}" for i in items)


@tool
async def search_knowledge_base(query: str, source: str = "all", limit: int = 6) -> str:
    """Busca na base de conhecimento pessoal e repositórios indexados (RAG: PDFs, apostilas, manuais, receitas, notas).

    Use quando o usuário perguntar sobre documentos indexados ou pedir para consultar suas coleções pessoais.

    Args:
        query: pergunta ou termos de busca.
        source: 'all' para buscar em todas as fontes ou o nome exato de uma coleção/fonte.
        limit: quantidade máxima de trechos retornados (1 a 12).
    """
    from .rag_bridge import rag_search_for_tool

    safe_limit = max(1, min(int(limit or 6), 12))
    return await rag_search_for_tool(workspace=None, query=query, limit=safe_limit, source=source or "all")


@tool
async def list_knowledge_sources() -> str:
    """Lista todas as coleções de documentos pessoais e repositórios indexados no RAG."""
    try:
        from backend.rag import get_service

        sources = await get_service().list_sources()
    except Exception as exc:  # noqa: BLE001
        return f"RAG indisponível no momento: {exc}"
    if not sources:
        return "Nenhuma fonte indexada ainda. O usuário pode enviar documentos em /static/rag.html."
    return "\n".join(f"- {s['name']} ({s['kind']}, {s['files']} arquivos, {s['chunks']} trechos)" for s in sources)


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


WEB_TOOLS = [web_search, web_fetch, youtube_transcript]
UTILITY_TOOLS = [current_datetime, calculate, read_attachment, list_chat_attachments, search_knowledge_base, list_knowledge_sources]
MEMORY_TOOLS = [remember_fact, list_memories, forget_fact]
ASSISTANT_TOOLS = WEB_TOOLS + UTILITY_TOOLS + MEMORY_TOOLS
