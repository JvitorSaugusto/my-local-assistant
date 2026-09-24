from pathlib import Path
import os
import re
import ast
import subprocess
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime


MAX_READS_PER_GENERATE_TASK = 50


def _count_read_calls(messages) -> int:
    return sum(
        1
        for msg in messages
        if getattr(msg, "tool_calls", None)
        for call in msg.tool_calls
        if call["name"] in ("read_file_content", "list_directory_files", "read_file_chunk")
    )

def _messages_since_last_human(state: dict) -> list:
    """Espelha o mesmo corte usado em generate_node/context_gatherer_node —
    conta só o que aconteceu na tarefa atual, não o histórico da conversa."""
    messages = state.get("messages", [])
    last_human_idx = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].type == "human":
            last_human_idx = i
            break
    return messages[last_human_idx:]
    
@tool
def list_directory_files(dir_path: str, runtime: ToolRuntime) -> list:
    """
    Lista todos os arquivos de código dentro de uma pasta e suas subpastas.
    Use esta ferramenta para descobrir a estrutura do diretório e ver quais arquivos existem 
    antes de decidir quais você precisa ler o conteúdo.
    
    Args:
        dir_path (str): O caminho da pasta que deve ser mapeada.
        
    Returns:
        list: Uma lista contendo os caminhos (paths) de todos os arquivos encontrados.
    """
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.php', '.html', '.css', '.sql'}
    IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env'}

    file_paths = []
    
    if _count_read_calls(runtime.state.get("messages", [])) >= MAX_READS_PER_GENERATE_TASK:
        return (
            "ERRO FATAL — LIMITE DE INVESTIGAÇÃO ATINGIDO: você já fez muitas "
            "chamadas de leitura nesta execução sem produzir uma edição. PARE de "
            "usar ferramentas de leitura. Se você já tem o suficiente, prossiga "
            "para criar/editar arquivos. Se não tem, reporte a tarefa como ambígua "
            "e encerre — não chame mais nenhuma ferramenta de leitura."
        )
    
    already_listed = any(
        call["name"] == "list_directory_files" and call["args"].get("dir_path") == dir_path
        for msg in _messages_since_last_human(runtime.state)
        if getattr(msg, "tool_calls", None)
        for call in msg.tool_calls
    )

    if already_listed:
        return (
            "AVISO: você já listou este diretório nesta mesma execução. "
            "Releitura desnecessária. Use a lista que você já obteve e avance: "
            "leia o arquivo específico necessário, edite/crie o arquivo, ou "
            "finalize se a investigação já é suficiente."
        )

    workspace_path = runtime.state.get("workspace_path")
    resolved_dir = _resolve_path(dir_path, workspace_path)
    
    print(f"[LEITURA] resolved_dir={resolved_dir}")

    for root, dirs, files in os.walk(resolved_dir):
        allowed_dirs = [d for d in dirs if d not in IGNORED_DIRS]
        dirs[:] = allowed_dirs

        for file_name in files:
            if Path(file_name).suffix in CODE_EXTENSIONS:
                file_path = Path(root) / file_name
                file_paths.append(str(file_path))
    
    read_count = _count_read_calls(_messages_since_last_human(runtime.state))
    print(f"[LEITURA] {read_count}/{MAX_READS_PER_GENERATE_TASK} chamadas nesta execução | resolved_dir={resolved_dir}")

    return file_paths

@tool
def read_file_content(file_path: str, runtime: ToolRuntime) -> str:
    """
    Lê e retorna o conteúdo COMPLETO de um arquivo pequeno.

    NÃO aceita offset/length. Para arquivos grandes, onde ler tudo de uma vez
    não é prático, use `read_file_chunk` em vez desta.

    Args:
        file_path (str): Caminho relativo do arquivo.

    Returns:
        str: Conteúdo completo do arquivo, ou mensagem de erro/orientação.
    """
    if _count_read_calls(runtime.state.get("messages", [])) >= MAX_READS_PER_GENERATE_TASK:
        return (
            "ERRO FATAL — LIMITE DE INVESTIGAÇÃO ATINGIDO: ..."
        )

    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    try:
        content = resolved_path.read_text(encoding='utf-8')
    except Exception as error:
        return f"Erro ao ler o arquivo: {str(error)}"

    total_lines = content.count("\n") + 1
    if total_lines > 400:
        return (
            f"Este arquivo tem {total_lines} linhas — grande demais para ler de uma vez. "
            f"Use a ferramenta `read_file_chunk(file_path, offset, length)` para ler em partes, "
            f"ou `search_in_file(file_path, pattern)` para localizar um trecho específico primeiro."
        )

    return content

@tool
def read_file_chunk(file_path: str, offset: int, length: int, runtime: ToolRuntime) -> str:
    """
    Lê um trecho específico (por linha) de um arquivo, numerado por linha.

    Use esta ferramenta para arquivos grandes, quando você já sabe (via
    `search_in_file` ou por contexto) aproximadamente onde procurar, e não
    precisa/quer o arquivo inteiro.

    Args:
        file_path (str): Caminho relativo do arquivo.
        offset (int): Número da primeira linha a retornar (1 = início do arquivo).
        length (int): Quantidade de linhas a retornar a partir do offset.

    Returns:
        str: Linhas no formato "N: conteúdo", mais um resumo indicando quantas
        linhas o arquivo tem no total e se o trecho retornado é o final dele.
    """
    if _count_read_calls(runtime.state.get("messages", [])) >= MAX_READS_PER_GENERATE_TASK:
        return (
            "ERRO FATAL — LIMITE DE INVESTIGAÇÃO ATINGIDO: ..."
        )

    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    try:
        lines = resolved_path.read_text(encoding='utf-8').splitlines()
    except Exception as error:
        return f"Erro ao ler o arquivo: {str(error)}"

    total_lines = len(lines)
    start = max(0, offset - 1)
    end = min(total_lines, start + length)

    if start >= total_lines:
        return f"O arquivo tem apenas {total_lines} linhas — offset {offset} está além do final."

    chunk = "\n".join(f"{i+1}: {lines[i]}" for i in range(start, end))
    footer = f"\n\n[linhas {start+1}-{end} de {total_lines} totais]"
    if end < total_lines:
        footer += " (arquivo continua além deste trecho)"

    return chunk + footer

@tool
def search_in_file(file_path: str, pattern: str, runtime: ToolRuntime) -> str:
    """
    Busca uma string ou regex dentro de um arquivo e retorna as linhas
    correspondentes com seus números de linha.

    Use esta ferramenta quando precisar LOCALIZAR onde algo está em um arquivo
    (ex: o início de uma classe, uma função, um texto específico), em vez de
    ler o arquivo inteiro ou tentar adivinhar a posição lendo em pedaços.

    Depois de localizar a linha certa aqui, use `read_file_chunk` com um
    offset próximo a ela para ver o contexto completo antes de editar.

    Args:
        file_path (str): Caminho relativo do arquivo.
        pattern (str): Texto ou regex a buscar.

    Returns:
        str: Linhas correspondentes, formatadas como "N: conteúdo da linha",
        ou uma mensagem indicando que nada foi encontrado.
    """
    import re

    if _count_read_calls(runtime.state.get("messages", [])) >= MAX_READS_PER_GENERATE_TASK:
        return (
            "ERRO FATAL — LIMITE DE INVESTIGAÇÃO ATINGIDO: você já fez muitas "
            "chamadas de leitura nesta execução sem produzir uma edição. PARE de "
            "usar ferramentas de leitura. Se você já tem o suficiente, prossiga "
            "para criar/editar arquivos. Se não tem, reporte a tarefa como ambígua "
            "e encerre — não chame mais nenhuma ferramenta de leitura."
        )

    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    print(f"[BUSCA] arquivo={resolved_path} pattern={pattern!r}")

    try:
        lines = resolved_path.read_text(encoding='utf-8').splitlines()
    except Exception as error:
        print(f"[BUSCA] FALHOU: {error}")
        return f"Erro ao ler o arquivo: {str(error)}"

    try:
        compiled = re.compile(pattern)
    except re.error as error:
        return f"Padrão de busca inválido: {error}"

    matches = [
        f"{i+1}: {line}"
        for i, line in enumerate(lines)
        if compiled.search(line)
    ]

    if not matches:
        print("[BUSCA] nenhuma ocorrência")
        return f"Nenhuma ocorrência de '{pattern}' encontrada em {file_path}."

    print(f"[BUSCA] {len(matches)} ocorrência(s) encontrada(s)")
    return "\n".join(matches)

@tool
def generate_repo_map(dir_path: str, runtime: ToolRuntime) -> str:
    """
    Gera um mapa estrutural do repositório, exibindo a árvore de arquivos e 
    as assinaturas de classes e funções, sem o corpo do código.
    Use isso para entender a arquitetura completa antes de decidir quais arquivos ler integralmente.
    
    Args:
        dir_path (str): O caminho da pasta que deve ser mapeada.
        
    Returns:
        str: Uma representação em texto da árvore do projeto com as assinaturas de código.
    """
    
    # already_mapped = any(
    #     call["name"] == "generate_repo_map" and call["args"].get("dir_path") == dir_path
    #     for msg in _messages_since_last_human(runtime.state)
    #     if getattr(msg, "tool_calls", None)
    #     for call in msg.tool_calls
    # )
    # if already_mapped:
    #     return (
    #         "AVISO: você já gerou o mapa deste diretório nesta mesma execução. "
    #         "Use o mapa que já obteve — não gere de novo. Se precisar de mais "
    #         "detalhes, leia um arquivo específico com read_file_content, ou "
    #         "finalize a investigação se já tem o suficiente."
    #     )
        
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.php', '.md'}
    IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env'}
    
    REGEX_FALLBACK = re.compile(
        r'^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+\w+'
        r'|^\s*(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>', 
        re.MULTILINE
    )

    workspace_path = runtime.state.get("workspace_path")
    resolved_dir = str(_resolve_path(dir_path, workspace_path))
    print(f"[LEITURA] resolved_dir={resolved_dir}")

    repo_map = [f"Mapa do Repositório: {dir_path}\n"]

    for root, dirs, files in os.walk(resolved_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        level = root.replace(resolved_dir, '').count(os.sep)
        indent = ' ' * 4 * level
        folder_name = os.path.basename(root)

        if folder_name:
            repo_map.append(f"{indent}📂 {folder_name}/")

        sub_indent = ' ' * 4 * (level + 1)

        for file_name in files:
            ext = Path(file_name).suffix
            if ext in CODE_EXTENSIONS:
                file_path = Path(root) / file_name
                repo_map.append(f"{sub_indent}📄 {file_name}")

                try:
                    content = file_path.read_text(encoding='utf-8')

                    if ext == '.py':
                        py_sigs = parse_python_ast(content, sub_indent)
                        repo_map.extend(py_sigs)
                    else:
                        signatures = REGEX_FALLBACK.findall(content)
                        for sig in signatures:
                            repo_map.append(f"{sub_indent}    🔹 {sig.strip()}")
                except Exception:
                    repo_map.append(f"{sub_indent}    ⚠️ (Erro ao ler arquivo)")

    return "\n".join(repo_map)

# ──────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS (não são tools — não ficam visíveis pro LLM)
# ──────────────────────────────────────────────────────────────────────────

PROTECTED_BRANCHES = {"main", "master"}

def _resolve_path(file_path: str, workspace_path: str | None) -> Path:
    """Resolve o caminho recebido do LLM contra o workspace da conversa.
    Se o LLM já mandou um caminho absoluto, usa como está; se mandou
    relativo (o comportamento esperado e mais comum), junta com o
    workspace_path do State."""
    path = Path(file_path)
    if path.is_absolute():
        return path
    if workspace_path:
        return Path(workspace_path) / path
    return path

def _find_existing_ancestor(path: Path) -> Path:
    """Sobe na árvore de diretórios até achar uma pasta que já existe —
    necessário porque, ao criar um arquivo novo, as pastas pai ainda podem
    não existir no momento da checagem de branch."""
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _get_current_branch(file_path: str) -> str | None:
    """Retorna o nome da branch git atual do repositório que contém
    file_path, ou None se não for possível determinar (não é um repositório
    git, ou o comando git não está disponível)."""
    start_dir = _find_existing_ancestor(Path(file_path).parent)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(start_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    return result.stdout.strip()


def _check_not_on_protected_branch(file_path: str) -> str | None:
    """Retorna uma mensagem de erro se o arquivo estiver numa branch
    protegida (main/master); retorna None se a edição pode prosseguir."""
    branch = _get_current_branch(file_path)

    if branch is not None and branch in PROTECTED_BRANCHES:
        return (
            "ERRO DE SEGURANÇA: Você não pode editar arquivos na branch "
            "main/master. Use a ferramenta 'create_git_branch' primeiro!"
        )

    return None


# ──────────────────────────────────────────────────────────────────────────
# TOOLS
# ──────────────────────────────────────────────────────────────────────────

GENERATE_BRANCHES: dict[str, str] = {}
GENERATE_BRANCH_CALLS: dict[str, int] = {}
MAX_BRANCH_CALLS_PER_TASK = 3

@tool
def create_git_branch(branch_name: str, runtime: ToolRuntime) -> str:
    """Cria uma nova branch git a partir da branch atual e muda para ela imediatamente.

    Use esta ferramenta OBRIGATORIAMENTE antes de qualquer edição de arquivo,
    assim que você receber uma nova tarefa. Nunca tente editar arquivos
    diretamente na branch 'main' ou 'master' — as ferramentas de escrita vão
    bloquear a operação automaticamente se você tentar. O repositório correto
    já é identificado automaticamente pelo sistema — você não precisa (e não
    consegue) informá-lo.

    Args:
        branch_name: Nome da nova branch, no padrão
            'feature/<resumo-curto-da-tarefa-atual>' (gere um resumo com base
            na tarefa que VOCÊ está executando agora — NUNCA reutilize um
            nome de exemplo genérico), em minúsculas, com palavras separadas
            por hífen, sem espaços ou acentos.

    Returns:
        Uma mensagem de sucesso confirmando a branch criada, ou uma mensagem
        de erro clara explicando o motivo da falha (branch já existe,
        caminho não é um repositório git, etc).
    """
    workspace_path = runtime.state.get("workspace_path")
    if not workspace_path:
        return "ERRO: nenhum workspace definido para esta conversa."

    repo = Path(workspace_path).resolve()
    repo_key = str(repo)
    
    existing_execution = GENERATE_BRANCHES.get(repo_key)
    if existing_execution:
        expected_branch = existing_execution["branch"]
        current_branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo), capture_output=True, text=True, timeout=10,
        )
        current_branch = current_branch_result.stdout.strip()

        if current_branch == expected_branch:
            return (
                f"Branch '{expected_branch}' já foi criada e continua ativa nesta execução. "
                "NÃO crie outra branch. Prossiga agora para investigar/editar os arquivos necessários."
            )

    calls = GENERATE_BRANCH_CALLS.get(repo_key, 0) + 1
    GENERATE_BRANCH_CALLS[repo_key] = calls

    if calls > MAX_BRANCH_CALLS_PER_TASK:
        return (
            "ERRO FATAL — EXECUÇÃO BLOQUEADA: você já chamou 'create_git_branch' "
            f"{calls} vezes nesta execução. Isso indica que você está criando "
            "branches em vez de prosseguir com a tarefa. NÃO chame mais esta "
            "ferramenta. Se já existe uma branch criada com sucesso, use-a e "
            "prossiga para investigar/editar arquivos. Se nenhuma branch foi "
            "criada com sucesso ainda, ENCERRE a execução agora e reporte a "
            "falha na sua resposta final, sem chamar nenhuma outra ferramenta."
        )

    if not repo.exists():
        return f"ERRO: o caminho '{workspace_path}' não existe."
    if not (repo / ".git").exists():
        return f"ERRO: '{workspace_path}' não é a raiz de um repositório git."

    base_commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    if base_commit_result.returncode != 0:
        return f"ERRO ao obter o commit atual: {base_commit_result.stderr.strip()}"
    base_commit = base_commit_result.stdout.strip()

    current_branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    current_branch = current_branch_result.stdout.strip()

    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(repo), capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return "ERRO: comando 'git' não encontrado."
    except subprocess.TimeoutExpired:
        return "ERRO: timeout no comando git."

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "already exists" in stderr:
            return f"ERRO: a branch '{branch_name}' já existe. Escolha outro nome."
        return f"ERRO ao criar a branch: {stderr}"


    current_branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    current_branch = current_branch_result.stdout.strip()

    if current_branch != branch_name:
        return (
            "ERRO DE SEGURANÇA: a branch foi criada, mas a branch atual "
            f"é '{current_branch}' em vez de '{branch_name}'."
        )

    GENERATE_BRANCHES[repo_key] = {"branch": branch_name, "base_commit": base_commit}

    return (
        f"Branch '{branch_name}' criada e ativada com sucesso. Commit base: {base_commit[:8]}. "
        "NÃO chame 'create_git_branch' novamente nesta execução — prossiga agora "
        "para investigar o projeto e editar os arquivos necessários."
    )


@tool
def create_new_file(file_path: str, content: str, runtime: ToolRuntime) -> str:
    """Cria um novo arquivo do zero com o conteúdo especificado.

    Use esta ferramenta apenas para arquivos que AINDA NÃO EXISTEM. Se o
    arquivo já existir, use 'edit_existing_file' ou 'append_to_file'.
    Os diretórios intermediários do caminho são criados automaticamente
    caso não existam.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a criação de
    arquivos enquanto a branch atual for 'main' ou 'master'. Use
    'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório, incluindo nome e
            extensão (ex: 'backend/api/routes/users.py'). O sistema já
            resolve isso automaticamente contra o repositório correto — NÃO
            inclua o caminho absoluto do disco.
        content: O conteúdo completo do arquivo, exatamente como deve ficar
            gravado em disco (incluindo indentação e quebras de linha).

    Returns:
        Uma mensagem de sucesso com o caminho do arquivo criado, ou uma
        mensagem de erro explicando o motivo da falha.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if resolved_path.exists():
        return (
            f"ERRO: o arquivo '{file_path}' já existe. Use 'edit_existing_file' "
            "ou 'append_to_file' para modificar um arquivo existente."
        )

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
    except OSError as error:
        return f"ERRO ao criar o arquivo '{file_path}': {error}"

    return f"Arquivo '{file_path}' criado com sucesso ({len(content)} caracteres)."


@tool
def edit_existing_file(file_path: str, old_snippet: str, new_snippet: str, runtime: ToolRuntime) -> str:
    """Edita um arquivo existente substituindo um trecho exato por outro (search and replace).

    Use esta ferramenta em vez de reescrever o arquivo inteiro — isso evita
    perder partes do arquivo que não deveriam mudar. O 'old_snippet' deve
    ser copiado EXATAMENTE como aparece no arquivo (mesma indentação, mesmas
    quebras de linha) — use o conteúdo retornado por 'read_file_content'
    como referência, nunca digite de memória. O trecho precisa ser único no
    arquivo: se aparecer mais de uma vez, inclua linhas extras de contexto
    antes/depois até que ele se torne único.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a edição enquanto a
    branch atual for 'main' ou 'master'. Use 'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório (ex: 'tasks.py'). O
            sistema já resolve isso automaticamente contra o repositório
            correto — NÃO inclua o caminho absoluto do disco.
        old_snippet: O trecho exato de texto já existente no arquivo que
            deve ser substituído.
        new_snippet: O novo trecho que deve tomar o lugar de 'old_snippet'.

    Returns:
        Uma mensagem de sucesso, ou um erro claro se o arquivo não existir,
        se 'old_snippet' não for encontrado, ou se aparecer mais de uma vez.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe. Use 'create_new_file' para criá-lo."
    
    try:
        original_content = resolved_path.read_text(encoding="utf-8")
    except OSError as error:
        return f"ERRO ao ler o arquivo '{file_path}': {error}"

    old_snippet = old_snippet.strip("\n\r")
    new_snippet = new_snippet.strip("\n\r")

    occurrences = original_content.count(old_snippet)

    if occurrences == 0:
        return (
            "ERRO: o trecho informado em 'old_snippet' não foi encontrado no "
            f"arquivo '{file_path}'. Confira se foi copiado exatamente como "
            "está no arquivo (indentação e quebras de linha incluídas)."
        )

    if occurrences > 1:
        return (
            f"ERRO: o trecho informado aparece {occurrences} vezes no arquivo "
            f"'{file_path}', e a edição precisa ser única. Inclua mais linhas "
            "de contexto antes ou depois do trecho para torná-lo único."
        )

    updated_content = original_content.replace(old_snippet, new_snippet)

    try:
        resolved_path.write_text(updated_content, encoding="utf-8")
    except OSError as error:
        return f"ERRO ao salvar o arquivo '{file_path}': {error}"

    return f"Arquivo '{file_path}' editado com sucesso."


@tool
def append_to_file(file_path: str, content: str, runtime: ToolRuntime) -> str:
    """Adiciona conteúdo ao final de um arquivo existente, sem alterar o que já está lá.

    Use esta ferramenta para casos simples de adição no final do arquivo,
    como uma nova rota em urls.py, uma nova variável em um .env, ou uma
    nova linha de log/configuração. Se o conteúdo precisar ser inserido no
    meio do arquivo, use 'edit_existing_file'.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a edição enquanto a
    branch atual for 'main' ou 'master'. Use 'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório. O sistema já
            resolve isso automaticamente contra o repositório correto — NÃO
            inclua o caminho absoluto do disco.
        content: O texto a ser adicionado ao final do arquivo. Inclua uma
            quebra de linha no início se o conteúdo precisar começar numa
            linha separada do que já existe.

    Returns:
        Uma mensagem de sucesso, ou um erro se o arquivo não existir.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe. Use 'create_new_file' para criá-lo."

    try:
        with resolved_path.open("a", encoding="utf-8") as file:
            file.write(content)
    except OSError as error:
        return f"ERRO ao adicionar conteúdo ao arquivo '{file_path}': {error}"

    return f"Conteúdo adicionado ao final de '{file_path}' com sucesso."


@tool
def git_commit_changes(commit_message: str, files_to_commit: list[str], runtime: ToolRuntime) -> str:
    """Cria um commit git APENAS com os arquivos especificados.

    Use esta ferramenta SOMENTE no final da tarefa, depois de já ter feito
    todas as edições necessárias com as outras ferramentas de escrita.

    Você DEVE passar explicitamente a lista dos arquivos que VOCÊ modificou
    ou criou. Nunca tente commitar arquivos em que você não trabalhou.

    O commit só é permitido em branches de desenvolvimento (nunca em main/master).

    A `commit_message` deve seguir o padrão Conventional Commits:
    - 'feat: ...' para uma nova funcionalidade;
    - 'fix: ...' para correção de bug;
    - 'refactor: ...' para mudança de estrutura sem alterar comportamento;
    - 'chore: ...' para tarefas de manutenção (configs, dependências);
    - 'docs: ...' para mudanças em documentação.

    Exemplo: 'docs: cria documentação técnica do módulo' 
    (Nota: A tag de identificação da inteligência artificial [🤖 IA] será 
    injetada automaticamente pelo sistema caso você não a inclua).

    Args:
        commit_message: Mensagem do commit seguindo Conventional Commits.
        files_to_commit: Lista de strings com os caminhos relativos dos 
            arquivos que você editou/criou.

    Returns:
        Uma mensagem de sucesso com a saída do commit, ou um erro detalhado.
    """
    workspace_path = runtime.state.get("workspace_path")

    if not workspace_path:
        return "ERRO: nenhum workspace definido para esta conversa."

    repo = Path(workspace_path).resolve()

    if not (repo / ".git").exists():
        return f"ERRO: '{workspace_path}' não é a raiz de um repositório git."

    if not files_to_commit:
        return (
            "ERRO: você deve fornecer a lista de arquivos "
            "em 'files_to_commit'."
        )

    try:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )

        if branch_result.returncode != 0:
            return (
                "ERRO DE SEGURANÇA: não foi possível verificar "
                "a branch atual."
            )

        current_branch = branch_result.stdout.strip()

        if current_branch in {"main", "master"}:
            return (
                f"ERRO DE SEGURANÇA: você não pode commitar diretamente "
                f"na branch '{current_branch}'. "
                "Crie uma branch de trabalho primeiro."
            )

        valid_files = []

        for file_path in files_to_commit:
            resolved_path = _resolve_path(file_path, workspace_path)

            if not resolved_path.exists():
                return (
                    f"ERRO: o arquivo '{file_path}' não existe "
                    "no workspace."
                )

            try:
                relative_path = resolved_path.relative_to(repo)
            except ValueError:
                return (
                    f"ERRO DE SEGURANÇA: o arquivo '{file_path}' "
                    "está fora do workspace."
                )

            valid_files.append(str(relative_path))

        add_command = ["git", "add", "--"] + valid_files

        add_result = subprocess.run(
            add_command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if add_result.returncode != 0:
            return (
                "ERRO ao executar git add para os arquivos "
                f"({valid_files}): {add_result.stderr.strip()}"
            )

        clean_message = commit_message.strip()

        if "[🤖 IA]" not in clean_message:
            if ":" in clean_message:
                prefix, description = clean_message.split(":", 1)
                clean_message = (
                    f"{prefix.strip()}: [🤖 IA] {description.strip()}"
                )
            else:
                clean_message = f"[🤖 IA] {clean_message}"

        commit_result = subprocess.run(
            ["git", "commit", "-m", clean_message],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if commit_result.returncode != 0:
            combined_output = (
                commit_result.stderr + commit_result.stdout
            ).lower()

            if "nothing to commit" in combined_output:
                return (
                    "AVISO: não havia nenhuma alteração real "
                    "nos arquivos especificados para commitar."
                )

            return (
                "ERRO ao criar o commit: "
                f"{commit_result.stderr.strip() or commit_result.stdout.strip()}"
            )

        return (
            f"Commit criado com sucesso na branch '{current_branch}'.\n"
            f"Arquivos commitados: {', '.join(valid_files)}\n"
            f"Mensagem: {clean_message}"
        )

    except FileNotFoundError:
        return (
            "ERRO: comando 'git' não encontrado. "
            "Verifique se o Git está instalado e no PATH."
        )

    except subprocess.TimeoutExpired:
        return (
            "ERRO: o comando git demorou demais para responder "
            "(timeout)."
        )

    except Exception as error:
        return (
            "ERRO inesperado na ferramenta de commit: "
            f"{str(error)}"
        )