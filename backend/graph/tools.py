from collections import Counter
from pathlib import Path
import os
import re
import ast
import shutil
import subprocess
import sys
import tempfile
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime


MAX_READS_PER_GENERATE_TASK = 50


def parse_python_ast(content: str, sub_indent: str) -> list[str]:
    """
    Faz o parse do código Python e extrai assinaturas de classes e funções
    sem precisar de expressões regulares.
    """
    signatures = []
    try:
        tree = ast.parse(content)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                signatures.append(f"{sub_indent}    🔹 class {node.name}:")
                for sub_node in node.body:
                    if isinstance(sub_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        signatures.append(f"{sub_indent}        🔸 def {sub_node.name}(...):")
            
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                signatures.append(f"{sub_indent}    🔹 {prefix} {node.name}(...):")
                
    except SyntaxError:
        signatures.append(f"{sub_indent}    ⚠️ (Erro de sintaxe no arquivo Python)")
    except Exception as e:
        signatures.append(f"{sub_indent}    ⚠️ (Erro ao parsear AST: {str(e)})")
        
    return signatures

def _count_read_calls(messages) -> int:
    return sum(
        1
        for msg in messages
        if getattr(msg, "tool_calls", None)
        for call in msg.tool_calls
        if call["name"] in ("read_file_content", "list_directory_files", "read_file_chunk","search_in_file", "generate_repo_map",)
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
    
    # Trava de segurança mantida antes da formatação
    if total_lines > 400:
        return (
            f"Este arquivo tem {total_lines} linhas — grande demais para ler de uma vez. "
            f"Use a ferramenta `read_file_chunk(file_path, offset, length)` para ler em partes, "
            f"ou `search_in_file(file_path, pattern)` para localizar um trecho específico primeiro."
        )

    # Aplica a numeração de linhas solicitada
    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(content.splitlines(), start=1))
    
    return numbered

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

    O caminho recebido é resolvido contra o workspace da conversa.
    """

    CODE_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".php", ".md"
    }

    IGNORED_DIRS = {
        ".git",
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        ".next",
        "dist",
        "build",
        "out",
        ".expo",
    }

    REGEX_FALLBACK = re.compile(
        r'^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+\w+'
        r'|^\s*(?:export\s+)?(?:const|let)\s+\w+\s*='
        r'\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>',
        re.MULTILINE,
    )

    workspace_path = runtime.state.get("workspace_path")

    if not workspace_path:
        return (
            "ERRO: nenhum workspace definido para esta conversa."
        )

    resolved_dir = _resolve_path(dir_path, workspace_path)

    print(f"[REPO MAP] dir_path={dir_path}")
    print(f"[REPO MAP] workspace={workspace_path}")
    print(f"[REPO MAP] resolved={resolved_dir}")

    if not resolved_dir.exists():
        return (
            f"ERRO: diretório não existe: '{dir_path}'\n"
            f"Caminho resolvido: '{resolved_dir}'"
        )

    if not resolved_dir.is_dir():
        return (
            f"ERRO: o caminho informado não é um diretório: '{dir_path}'\n"
            f"Caminho resolvido: '{resolved_dir}'"
        )

    repo_map = [
        f"Mapa do Repositório: {dir_path}",
        f"Caminho Resolvido: {resolved_dir}",
        "",
    ]

    for root, dirs, files in os.walk(resolved_dir):
        dirs[:] = [
            d for d in dirs
            if d not in IGNORED_DIRS
        ]

        level = root.replace(str(resolved_dir), "").count(os.sep)
        indent = " " * 4 * level
        folder_name = os.path.basename(root)

        if folder_name:
            repo_map.append(f"{indent}📂 {folder_name}/")

        sub_indent = " " * 4 * (level + 1)

        for file_name in sorted(files):
            ext = Path(file_name).suffix.lower()

            if ext not in CODE_EXTENSIONS:
                continue

            file_path = Path(root) / file_name

            repo_map.append(
                f"{sub_indent}📄 {file_name}"
            )

            try:
                content = file_path.read_text(
                    encoding="utf-8"
                )

                if ext == ".py":
                    signatures = parse_python_ast(
                        content,
                        sub_indent
                    )

                    repo_map.extend(signatures)

                else:
                    signatures = REGEX_FALLBACK.findall(
                        content
                    )

                    for sig in signatures:
                        repo_map.append(
                            f"{sub_indent}    🔹 {sig.strip()}"
                        )

            except Exception as error:
                repo_map.append(
                    f"{sub_indent}    ⚠️ "
                    f"(Erro ao ler arquivo: {error})"
                )

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
        
        if current_branch and current_branch not in PROTECTED_BRANCHES:  # 👈 restaurar
            return (
                "ERRO DE SEGURANÇA: o repositório já está em uma branch não protegida "
                f"('{current_branch}'). Não crie outra branch nesta execução. "
                "Prossiga usando a branch atual."
            )

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


# ──────────────────────────────────────────────────────────────────────────
# GUARDAS DE EDIÇÃO
# Objetivo: nunca gravar em disco um .py com sintaxe quebrada, função
# duplicada no mesmo escopo, função "engolida" por outra (indentação errada)
# ou edição aplicada em linhas deslocadas (número de linha desatualizado).
# ──────────────────────────────────────────────────────────────────────────

INDENT_SENSITIVE_SUFFIXES = {".py", ".yml", ".yaml"}
_SPECIAL_DECORATORS = {"setter", "getter", "deleter", "register", "overload"}
_LINE_NUMBER_PREFIX = re.compile(r"^\s*\d+: ?")


def _read_text_keep_newline(path: Path) -> tuple[str, str]:
    """Lê o arquivo normalizando para '\\n' e devolve também o estilo
    de quebra de linha original ('\\r\\n' ou '\\n') para regravar igual."""
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def _write_text_atomic(path: Path, text: str, newline: str = "\n") -> None:
    """Grava via arquivo temporário + os.replace: nunca deixa o arquivo
    pela metade se algo falhar no meio da escrita."""
    data = text.replace("\n", newline) if newline != "\n" else text
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(data.encode("utf-8"))
        if path.exists():
            shutil.copymode(path, tmp_name)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _strip_line_number_prefix(text: str) -> str:
    """Remove o prefixo 'N: ' que as ferramentas de leitura adicionam,
    caso o modelo o tenha copiado junto com o código."""
    return _LINE_NUMBER_PREFIX.sub("", text, count=1)


def _strip_line_numbers_block(text: str) -> str:
    """Remove 'N: ' de TODAS as linhas de um bloco, mas só quando o bloco
    inteiro parece copiado da leitura (>= 2 linhas, números consecutivos).
    Evita estragar código legítimo como `1: "a",` num dicionário."""
    lines = text.split("\n")
    non_blank = [ln for ln in lines if ln.strip()]
    if len(non_blank) < 2:
        return text

    numbers = []
    for ln in non_blank:
        match = re.match(r"^\s*(\d+):(?: |$)", ln)
        if not match:
            return text
        numbers.append(int(match.group(1)))

    if any(b - a != 1 for a, b in zip(numbers, numbers[1:])):
        return text

    return "\n".join(_LINE_NUMBER_PREFIX.sub("", ln, count=1) for ln in lines)


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _reindent_block(new_content: str, base_indent: str) -> tuple[str, str | None]:
    """Alinha a indentação do bloco novo com a da primeira linha substituída.
    Retorna (bloco, descrição_do_ajuste | None)."""
    block_lines = new_content.split("\n")
    non_blank = [ln for ln in block_lines if ln.strip()]
    if not non_blank:
        return new_content, None

    first_indent = _leading_ws(non_blank[0])
    if first_indent == base_indent:
        return new_content, None

    if len(first_indent) < len(base_indent) and base_indent.startswith(first_indent):
        extra = base_indent[len(first_indent):]
        shifted = [(extra + ln) if ln.strip() else ln for ln in block_lines]
        note = f"indentação ajustada: +{len(extra)} espaço(s) em todas as linhas do bloco"
        return "\n".join(shifted), note

    if first_indent.startswith(base_indent):
        remove = first_indent[len(base_indent):]
        if all(ln.startswith(remove) for ln in non_blank):
            shifted = [ln[len(remove):] if ln.strip() else ln for ln in block_lines]
            note = f"indentação ajustada: -{len(remove)} espaço(s) em todas as linhas do bloco"
            return "\n".join(shifted), note

    return new_content, None


def _has_special_decorator(node: ast.AST) -> bool:
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute):
            name = target.attr
        else:
            name = getattr(target, "id", "")
        if name in _SPECIAL_DECORATORS:
            return True
    return False


def _collect_definitions(tree: ast.AST):
    """Conta quantas vezes cada def/class é definida DIRETAMENTE em cada escopo
    (módulo, classe ou função) e quais escopos são funções."""
    counts: Counter = Counter()
    function_scopes: set[tuple[str, ...]] = set()

    def visit(body, scope: tuple[str, ...]) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not _has_special_decorator(stmt):
                    counts[(scope, stmt.name)] += 1
                child = scope + (stmt.name,)
                if not isinstance(stmt, ast.ClassDef):
                    function_scopes.add(child)
                visit(stmt.body, child)

    visit(tree.body, ())
    return counts, function_scopes


def _scope_label(scope: tuple[str, ...]) -> str:
    return ".".join(scope) if scope else "<nível do módulo>"


def _format_syntax_error(exc: SyntaxError, source: str, context: int = 2) -> str:
    lineno = exc.lineno or 0
    message = f"Erro de sintaxe na linha {lineno}: {exc.msg}"
    lines = source.splitlines()
    if 1 <= lineno <= len(lines):
        lo = max(1, lineno - context)
        hi = min(len(lines), lineno + context)
        snippet = "\n".join(
            f"{'>>' if i == lineno else '  '} {i}: {lines[i - 1]}"
            for i in range(lo, hi + 1)
        )
        message += "\n(numeração do arquivo COMO FICARIA; nada foi salvo)\n" + snippet
    return message


def _validate_python_edit(before: str, after: str) -> tuple[str | None, str | None]:
    """Valida o resultado de uma edição em arquivo Python.
    Retorna (erro, aviso). Se `erro` vier preenchido, a edição NÃO deve ser salva."""
    try:
        tree_after = ast.parse(after)
    except (SyntaxError, ValueError) as exc:
        detail = (
            _format_syntax_error(exc, after)
            if isinstance(exc, SyntaxError)
            else f"Erro ao analisar o código: {exc}"
        )
        try:
            ast.parse(before)
        except (SyntaxError, ValueError):
            return None, (
                "AVISO: o arquivo continua com erro de sintaxe (ele já estava "
                "quebrado ANTES desta edição).\n" + detail
            )
        return (
            "ERRO: edição REJEITADA — o arquivo ficaria com erro de sintaxe. "
            "NADA foi salvo.\n" + detail + "\n"
            "Corrija o conteúdo novo (blocos completos, indentação coerente com "
            "o código ao redor, parênteses/aspas fechados) e tente de novo.",
            None,
        )

    try:
        tree_before = ast.parse(before)
    except (SyntaxError, ValueError):
        return None, None

    counts_before, _ = _collect_definitions(tree_before)
    counts_after, function_scopes_after = _collect_definitions(tree_after)

    problems: list[str] = []

    late_imports = _late_new_imports(tree_before, tree_after)
    if late_imports:
        listing = "\n".join(
            f"  linha {n.lineno}: {ast.unparse(n)}" for n in late_imports[:5]
        )
        return (
            "ERRO: edição REJEITADA — import(s) novo(s) ficariam DEPOIS de "
            "funções/classes, no meio ou no fim do arquivo:\n" + listing + "\n"
            "Imports ficam no TOPO do arquivo. Para só adicionar imports use "
            "'append_to_file' com SOMENTE as linhas de import (a ferramenta os "
            "coloca junto aos imports do topo), ou edite o bloco de imports do "
            "topo com 'edit_existing_file'. NADA foi salvo.",
            None,
        )

    for key, total in sorted(counts_after.items()):
        if total > 1 and total > counts_before.get(key, 0):
            scope, name = key
            problems.append(
                f"'{name}' ficaria definido {total}x em '{_scope_label(scope)}' "
                "(duplicação: o conteúdo novo repete algo que já existe fora do "
                "intervalo substituído — provavelmente o intervalo de linhas "
                "estava errado ou curto demais)"
            )

    for (scope, name) in counts_before:
        if (scope, name) in counts_after:
            continue
        for (scope2, name2) in counts_after:
            if (
                name2 == name
                and len(scope2) > len(scope)
                and scope2[: len(scope)] == scope
                and scope2 in function_scopes_after
            ):
                problems.append(
                    f"'{name}' deixaria de existir em '{_scope_label(scope)}' e "
                    f"passaria a ficar ANINHADA dentro da função "
                    f"'{_scope_label(scope2)}' (indentação errada ou intervalo de "
                    "linhas que cortou o bloco no meio)"
                )
                break

    if problems:
        return (
            "ERRO: edição REJEITADA — a estrutura do arquivo ficaria inconsistente. "
            "NADA foi salvo.\n" + "\n".join(f"- {p}" for p in problems) + "\n"
            "Releia o trecho com 'read_file_chunk' (os números de linha mudam "
            "após cada edição) e refaça a chamada com o intervalo completo "
            "e correto.",
            None,
        )

    nested_new = sorted(
        (scope, name)
        for (scope, name) in counts_after
        if (scope, name) not in counts_before and scope in function_scopes_after
    )
    if nested_new:
        labels = ", ".join(
            f"'{name}' (dentro de '{_scope_label(scope)}')" for scope, name in nested_new
        )
        return None, (
            f"AVISO: definição(ões) nova(s) ficaram ANINHADAS em função: {labels}. "
            "Se a intenção era definir no nível do módulo/classe, a indentação "
            "está errada — corrija com 'edit_existing_file'."
        )

    return None, None


_IMPORT_NODES = (ast.Import, ast.ImportFrom)
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _first_def_line(tree: ast.Module) -> int | None:
    lines = [
        min([node.lineno] + [d.lineno for d in node.decorator_list])
        for node in tree.body
        if isinstance(node, _DEF_NODES)
    ]
    return min(lines) if lines else None


def _late_new_imports(tree_before: ast.Module, tree_after: ast.Module) -> list[ast.stmt]:
    """Imports de módulo NOVOS que ficariam depois da 1ª função/classe."""
    first_def = _first_def_line(tree_after)
    if first_def is None:
        return []
    known = {ast.dump(n) for n in tree_before.body if isinstance(n, _IMPORT_NODES)}
    return [
        n for n in tree_after.body
        if isinstance(n, _IMPORT_NODES) and n.lineno > first_def and ast.dump(n) not in known
    ]


def _insert_imports_at_top(original: str, addition: str) -> tuple[str, int, int] | None:
    """Se `addition` for SÓ imports, devolve (novo_texto, linha_inserida, qtd)
    colocando-os junto aos imports do topo (e ignorando os que já existem).
    Retorna None se `addition` tiver qualquer outra coisa além de imports."""
    try:
        tree_add = ast.parse(addition)
        tree_orig = ast.parse(original)
    except (SyntaxError, ValueError):
        return None

    if not tree_add.body or not all(isinstance(n, _IMPORT_NODES) for n in tree_add.body):
        return None

    existing = {ast.dump(n) for n in tree_orig.body if isinstance(n, _IMPORT_NODES)}
    add_lines = addition.splitlines()
    chunks = [
        "\n".join(add_lines[n.lineno - 1 : n.end_lineno])
        for n in tree_add.body
        if ast.dump(n) not in existing
    ]
    if not chunks:
        return original, 0, 0

    first_def = _first_def_line(tree_orig)
    top_imports = [
        n for n in tree_orig.body
        if isinstance(n, _IMPORT_NODES) and (first_def is None or n.lineno < first_def)
    ]

    lines = original.splitlines(keepends=True)
    if top_imports:
        index = top_imports[-1].end_lineno
    else:
        index = 0
        body = tree_orig.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(getattr(body[0], "value", None), ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            index = body[0].end_lineno

    if index and not lines[index - 1].endswith("\n"):
        lines[index - 1] += "\n"
    lines.insert(index, "\n".join(chunks) + "\n")
    return "".join(lines), index + 1, len(chunks)


def _numbered_window(text: str, first: int, last: int, max_lines: int = 60) -> str:
    lines = text.splitlines()
    first = max(1, first)
    last = min(len(lines), last)
    truncated = False
    if last - first + 1 > max_lines:
        last = first + max_lines - 1
        truncated = True
    body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(first, last + 1))
    if truncated:
        body += "\n... (trecho truncado; use 'read_file_chunk' para ver o restante)"
    return body


_TRIVIAL_LINES = {
    "pass", "else:", "try:", "finally:", "return", "break", "continue", "...",
    '"""', "'''", "return None", "return True", "return False", "return []",
    "return {}", "return \"\"", "return 0",
}


def _is_significant(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 8 and stripped not in _TRIVIAL_LINES


def _non_blank_before(lines: list[str], start_line: int, limit: int) -> list[str]:
    """Até `limit` linhas não vazias imediatamente ANTES do intervalo (em ordem)."""
    found: list[str] = []
    for i in range(start_line - 2, -1, -1):
        if lines[i].strip():
            found.append(lines[i].rstrip())
            if len(found) == limit:
                break
    return list(reversed(found))


def _non_blank_after(lines: list[str], end_line: int, limit: int) -> list[str]:
    """Até `limit` linhas não vazias imediatamente DEPOIS do intervalo."""
    found: list[str] = []
    for i in range(end_line, len(lines)):
        if lines[i].strip():
            found.append(lines[i].rstrip())
            if len(found) == limit:
                break
    return found


def _check_boundary_overlap(
    lines: list[str], start_line: int, end_line: int, new_block: str
) -> str | None:
    """Detecta o sintoma clássico de intervalo curto/longo demais: o INÍCIO ou o
    FIM do conteúdo novo repete as linhas vizinhas do intervalo (uma ou várias,
    com a mesma indentação), ou seja, sobrou/duplicou um pedaço do bloco antigo."""
    new_lines = [ln.rstrip() for ln in new_block.split("\n") if ln.strip()]
    if not new_lines:
        return None

    max_k = 6

    def meaningful(chunk: list[str]) -> bool:
        # 1 linha: precisa ser significativa. 2+ linhas: basta uma significativa.
        return any(_is_significant(ln) for ln in chunk)

    following = _non_blank_after(lines, end_line, max_k)
    tail_k = 0
    for k in range(1, min(max_k, len(new_lines), len(following)) + 1):
        if new_lines[-k:] == following[:k] and meaningful(following[:k]):
            tail_k = k

    if tail_k:
        dup = "\n".join(new_lines[-tail_k:])
        return (
            "ERRO: edição REJEITADA — o FIM do conteúdo novo repete "
            f"{tail_k} linha(s) que já existem logo APÓS o intervalo:\n{dup}\n"
            "Isso indica que o intervalo ficou curto e SOBRARIA parte do bloco "
            "antigo (duplicação). Estenda 'end_line' até o fim do bloco ou "
            "remova as linhas repetidas do 'new_content'. NADA foi salvo."
        )

    preceding = _non_blank_before(lines, start_line, max_k)
    head_k = 0
    for k in range(1, min(max_k, len(new_lines), len(preceding)) + 1):
        if new_lines[:k] == preceding[-k:] and meaningful(preceding[-k:]):
            head_k = k

    if head_k:
        dup = "\n".join(new_lines[:head_k])
        return (
            "ERRO: edição REJEITADA — o INÍCIO do conteúdo novo repete "
            f"{head_k} linha(s) que já existem logo ANTES do intervalo:\n{dup}\n"
            "Isso indica que o intervalo começou tarde demais e essas linhas "
            "ficariam duplicadas. Ajuste 'start_line' ou remova as linhas "
            "repetidas do 'new_content'. NADA foi salvo."
        )

    return None


def _normalize_expected(expected: str, line_no: int | None) -> str:
    """Remove o prefixo 'N: ' copiado da leitura — mas SÓ se o número for o da
    linha esperada, para não estragar código legítimo como `1: "a",`."""
    text = expected.rstrip("\r\n")
    match = _LINE_NUMBER_PREFIX.match(text)
    if match:
        number = int(re.match(r"\s*(\d+)", text).group(1))
        if line_no is None or number == line_no:
            text = text[match.end():]
    return text


def _lines_match(
    actual: str, expected: str, line_no: int | None = None, strict: bool = False
) -> bool:
    """Compara a linha real com o texto informado pelo modelo.

    strict=True  -> exige indentação idêntica (só ignora espaços no fim).
    strict=False -> aceita indentação diferente (o modelo costuma perdê-la),
                    mas nunca casa linhas vazias."""
    actual_text = actual.rstrip("\r\n").rstrip()
    expected_text = _normalize_expected(expected, line_no).rstrip()
    if actual_text == expected_text:
        return bool(actual_text.strip())
    if strict:
        return False
    return bool(actual_text.strip()) and actual_text.strip() == expected_text.strip()


def _find_shifted_range(
    lines: list[str],
    span: int,
    first_text: str,
    last_text: str,
    orig_start: int | None = None,
    orig_end: int | None = None,
) -> list[tuple[int, int]]:
    """Procura onde o bloco (mesma quantidade de linhas, mesma 1ª e última
    linha) está AGORA — caso os números de linha tenham ficado desatualizados.

    Só aceita busca "frouxa" (sem indentação) quando as duas pontas são linhas
    significativas; linhas triviais ('pass', 'return', '}') casariam em
    qualquer lugar e levariam a edição para o ponto errado."""

    def search(strict: bool) -> list[tuple[int, int]]:
        hits = []
        for start in range(1, len(lines) - span + 2):
            end = start + span - 1
            if _lines_match(lines[start - 1], first_text, orig_start, strict) and \
                    _lines_match(lines[end - 1], last_text, orig_end, strict):
                hits.append((start, end))
        return hits

    hits = search(strict=True)
    if hits:
        return hits

    if _is_significant(_normalize_expected(first_text, orig_start)) and \
            _is_significant(_normalize_expected(last_text, orig_end)):
        return search(strict=False)
    return []


@tool
def create_new_file(file_path: str, content: str, runtime: ToolRuntime) -> str:
    """Cria um novo arquivo do zero com o conteúdo especificado.

    Use esta ferramenta apenas para arquivos que AINDA NÃO EXISTEM. Se o
    arquivo já existir, use 'edit_existing_file' ou 'append_to_file'.
    Os diretórios intermediários do caminho são criados automaticamente
    caso não existam.

    Para arquivos .py o conteúdo é validado antes de gravar: sintaxe inválida
    ou funções/classes duplicadas no mesmo escopo fazem a criação ser rejeitada.

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

    content = _strip_line_numbers_block(content)

    if resolved_path.suffix == ".py":
        error, _warning = _validate_python_edit("", content)
        if error:
            return error

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
    except OSError as error:
        return f"ERRO ao criar o arquivo '{file_path}': {error}"

    return f"Arquivo '{file_path}' criado com sucesso ({len(content)} caracteres)."


@tool
def edit_existing_file(
    file_path: str,
    start_line: int,
    end_line: int,
    first_line_text: str,
    last_line_text: str,
    new_content: str,
    runtime: ToolRuntime,
) -> str:
    """Substitui um intervalo de linhas (inclusive) por um novo conteúdo em um arquivo existente.

    Ferramenta PRINCIPAL de edição. Para evitar editar o lugar errado quando os
    números de linha ficam desatualizados (cada edição desloca as linhas
    seguintes), você DEVE informar o texto atual da primeira e da última linha
    do intervalo. A ferramenta confere esses textos antes de gravar:
      - se baterem, a edição é aplicada;
      - se as linhas tiverem se deslocado mas o bloco ainda existir em UM único
        lugar, a edição é aplicada no lugar certo e isso é informado;
      - caso contrário, NADA é alterado e o trecho atual é devolvido.

    Para arquivos .py o resultado é validado ANTES de gravar: sintaxe inválida,
    função/classe duplicada no mesmo escopo ou função que ficaria aninhada
    dentro de outra fazem a edição ser REJEITADA (nada é salvo).

    Regras para um bom resultado:
      - Para substituir uma função/método/classe, o intervalo deve cobrir o
        bloco INTEIRO (da linha 'def'/decorator até a última linha do corpo),
        e 'new_content' deve conter o bloco inteiro novo. Nunca deixe sobrar
        metade do bloco antigo.
      - 'new_content' deve vir com a indentação REAL que ficará no arquivo.
        Se a indentação da primeira linha divergir da linha substituída, a
        ferramenta realinha o bloco inteiro e avisa.
      - Não inclua o prefixo 'N: ' das ferramentas de leitura.
      - 'new_content' vazio REMOVE as linhas do intervalo.
      - 'first_line_text'/'last_line_text' são conferidos com a indentação; se
        a linha for genérica ('pass', 'return', '}'), informe o número de linha
        correto e releia antes de editar. NÃO repita no 'new_content' linhas que
        já existem logo antes/depois do intervalo.
      - Imports novos em .py vão para o TOPO do arquivo (edite o bloco de imports).

    Args:
        file_path: Caminho relativo à raiz do repositório.
        start_line: Número da PRIMEIRA linha a substituir (formato "N: conteúdo"
            retornado pelas ferramentas de leitura).
        end_line: Número da ÚLTIMA linha a substituir (inclusive). Para
            substituir só uma linha, use o mesmo valor de start_line.
        first_line_text: Texto EXATO atual da linha start_line, copiado da
            leitura (sem o prefixo 'N: ').
        last_line_text: Texto EXATO atual da linha end_line, copiado da leitura
            (sem o prefixo 'N: '). Para uma única linha, repita first_line_text.
        new_content: Novo conteúdo que substituirá TODO o intervalo.

    Returns:
        Confirmação com o trecho resultante já com os NOVOS números de linha,
        ou mensagem de erro explicando por que nada foi alterado.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe."

    try:
        text, newline = _read_text_keep_newline(resolved_path)
    except (OSError, UnicodeDecodeError) as error:
        return f"ERRO ao ler o arquivo '{file_path}': {error}"

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if start_line < 1 or end_line < start_line or end_line > total_lines:
        return (
            f"ERRO: intervalo inválido (start_line={start_line}, end_line={end_line}). "
            f"O arquivo tem {total_lines} linhas. Releia com 'read_file_chunk' "
            "para confirmar os números corretos."
        )

    notes: list[str] = []

    # ── 1. Confere se o intervalo ainda é o que o modelo acha que é ──────────
    ends_match = _lines_match(
        lines[start_line - 1], first_line_text, start_line
    ) and _lines_match(lines[end_line - 1], last_line_text, end_line)

    if not ends_match:
        span = end_line - start_line + 1
        hits = _find_shifted_range(
            lines, span, first_line_text, last_line_text, start_line, end_line
        )

        if len(hits) == 1:
            new_start, new_end = hits[0]
            notes.append(
                f"Linhas DESLOCADAS: o bloco informado não estava mais em "
                f"{start_line}-{end_line}; foi localizado e editado em "
                f"{new_start}-{new_end}."
            )
            start_line, end_line = new_start, new_end
        else:
            hint = ""
            if len(hits) > 1:
                hint = (
                    f"\nO mesmo par de linhas aparece em {len(hits)} lugares: "
                    + ", ".join(f"{a}-{b}" for a, b in hits[:5])
                    + ". Informe o intervalo correto."
                )
            return (
                "ERRO: o conteúdo atual do intervalo NÃO bate com "
                "'first_line_text'/'last_line_text'. NADA foi alterado.\n"
                f"Linha {start_line} (atual): {lines[start_line - 1].rstrip()}\n"
                f"Linha {end_line} (atual): {lines[end_line - 1].rstrip()}\n"
                "Os números de linha mudam após cada edição. Releia a região "
                "com 'read_file_chunk' / 'search_in_file' e refaça a chamada."
                + hint
            )

    # ── 2. Monta o bloco novo ───────────────────────────────────────────────
    new_content = _strip_line_numbers_block(new_content).replace("\r\n", "\n")
    removed_block = "".join(lines[start_line - 1 : end_line])

    candidates: list[tuple[str, str | None]] = []

    if resolved_path.suffix in INDENT_SENSITIVE_SUFFIXES and new_content.strip():
        base_indent = _leading_ws(lines[start_line - 1])
        reindented, reindent_note = _reindent_block(new_content, base_indent)
        if reindent_note:
            candidates.append((reindented, reindent_note))

    candidates.append((new_content, None))

    final_error: str | None = None
    chosen_after: str | None = None
    chosen_block: str | None = None
    chosen_warning: str | None = None

    for block_text, block_note in candidates:
        if block_text.strip():
            new_block = block_text if block_text.endswith("\n") else block_text + "\n"
        else:
            new_block = ""

        updated_lines = lines[: start_line - 1] + ([new_block] if new_block else []) + lines[end_line:]
        after = "".join(updated_lines)

        warning = None
        error = _check_boundary_overlap(lines, start_line, end_line, new_block)
        if error is None and resolved_path.suffix == ".py":
            error, warning = _validate_python_edit(text, after)

        if error is None:
            chosen_after, chosen_block, chosen_warning = after, new_block, warning
            if block_note:
                notes.append(block_note)
            break

        if final_error is None or block_note is None:
            final_error = error

    if chosen_after is None or chosen_block is None:
        return final_error or "ERRO: edição rejeitada. NADA foi salvo."

    # ── 3. Grava ────────────────────────────────────────────────────────────
    try:
        _write_text_atomic(resolved_path, chosen_after, newline)
    except OSError as error:
        return f"ERRO ao salvar '{file_path}': {error}"

    new_count = len(chosen_block.splitlines())
    old_count = end_line - start_line + 1
    delta = new_count - old_count

    if chosen_warning:
        notes.append(chosen_warning)
    if not chosen_block:
        notes.append("Intervalo REMOVIDO (new_content vazio).")

    window = _numbered_window(
        chosen_after, start_line - 2, start_line + max(new_count, 1) + 1
    )

    shift_info = (
        f"As linhas APÓS esta edição foram deslocadas em {delta:+d}. "
        "Releia antes de usar números de linha posteriores a "
        f"{end_line}." if delta else "Nenhum deslocamento nas linhas seguintes."
    )

    return (
        f"Arquivo '{file_path}' editado: {old_count} linha(s) "
        f"({start_line}-{end_line}) substituída(s) por {new_count}.\n"
        + ("\n".join(notes) + "\n" if notes else "")
        + shift_info
        + "\n\nTrecho resultante (números JÁ ATUALIZADOS):\n"
        + window
        + ("\n\n(Removido:\n" + removed_block.rstrip("\n") + "\n)" if len(removed_block) < 600 else "")
    )


@tool
def batch_edit_file(file_path: str, edits: list[dict], runtime: ToolRuntime) -> str:
    """Aplica múltiplas substituições de texto (search and replace) em um único arquivo, numa só chamada.

    Use esta ferramenta em vez de várias chamadas separadas de 'edit_existing_file'
    quando precisar fazer MUITAS edições pequenas e independentes no MESMO arquivo
    (ex: adicionar um parâmetro em várias declarações de método, ajustar várias
    chamadas de função). Cada chamada de ferramenta consome uma etapa do limite de
    execução do agente — agrupar edições numa única chamada evita estourar esse
    limite em refatorações grandes.

    Use 'edit_existing_file' (não esta) quando precisar editar apenas um ou dois
    trechos no arquivo, ou substituir funções/blocos inteiros.

    As edições são aplicadas NA ORDEM em que aparecem na lista, uma após a outra,
    sobre o conteúdo já parcialmente editado pelas edições anteriores. Cada
    'old_snippet' deve ser copiado EXATAMENTE do conteúdo retornado por
    'read_file_content' (mesma indentação, mesmas quebras de linha) e deve ser
    único no momento em que for aplicado — se uma edição anterior já mudou o
    trecho, a próxima 'old_snippet' precisa refletir o texto já atualizado.

    Para arquivos .py o resultado FINAL é validado antes de gravar (sintaxe,
    definições duplicadas, função aninhada por engano). Se algo falhar, nada é salvo.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a edição enquanto a
    branch atual for 'main' ou 'master'. Use 'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório (ex: 'backend/api/services.py').
        edits: Lista de objetos, cada um com as chaves 'old_snippet' e 'new_snippet'
            (ex: [{"old_snippet": "def foo():", "new_snippet": "def foo(self):"}, ...]).
            Inclua quantas edições forem necessárias nesta única chamada.

    Returns:
        Um relatório do resultado de cada edição. Se QUALQUER edição falhar, NENHUMA
        edição desta chamada é salva no arquivo (tudo ou nada) — evita deixar o
        arquivo num estado parcialmente editado e inconsistente.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe. Use 'create_new_file' para criá-lo."

    if not edits:
        return "ERRO: a lista 'edits' está vazia. Forneça ao menos uma edição."

    try:
        original_content, newline = _read_text_keep_newline(resolved_path)
    except (OSError, UnicodeDecodeError) as error:
        return f"ERRO ao ler o arquivo '{file_path}': {error}"

    working_content = original_content
    report_lines = []
    for index, edit in enumerate(edits, start=1):
        old_snippet = (edit.get("old_snippet") or "").replace("\r\n", "\n").strip("\n")
        new_snippet = (edit.get("new_snippet") or "").replace("\r\n", "\n").strip("\n")

        if not old_snippet:
            report_lines.append(f"[{index}] ERRO: 'old_snippet' vazio.")
            return "FALHA — nenhuma edição foi salva.\n" + "\n".join(report_lines)

        occurrences = working_content.count(old_snippet)

        if occurrences == 0:
            report_lines.append(
                f"[{index}] ERRO: trecho não encontrado (pode já ter sido alterado "
                "por uma edição anterior desta mesma chamada, ou copiado incorretamente)."
            )
            return "FALHA — nenhuma edição foi salva.\n" + "\n".join(report_lines)

        if occurrences > 1:
            report_lines.append(
                f"[{index}] ERRO: trecho aparece {occurrences} vezes — precisa ser único "
                "neste ponto da edição. Adicione mais contexto."
            )
            return "FALHA — nenhuma edição foi salva.\n" + "\n".join(report_lines)

        working_content = working_content.replace(old_snippet, new_snippet, 1)
        report_lines.append(f"[{index}] OK")

    if resolved_path.suffix == ".py":
        error, warning = _validate_python_edit(original_content, working_content)
        if error:
            return "FALHA — nenhuma edição foi salva.\n" + "\n".join(report_lines) + "\n" + error
        if warning:
            report_lines.append(warning)

    try:
        _write_text_atomic(resolved_path, working_content, newline)
    except OSError as error:
        return f"ERRO ao salvar o arquivo '{file_path}' após aplicar as edições: {error}"

    report_lines.append(f"\nArquivo '{file_path}' salvo com sucesso — {len(edits)} edição(ões) aplicada(s).")
    return "\n".join(report_lines)


@tool
def append_to_file(file_path: str, content: str, runtime: ToolRuntime) -> str:
    """Adiciona conteúdo ao final de um arquivo existente, sem alterar o que já está lá.

    Use esta ferramenta para casos simples de adição no final do arquivo,
    como uma nova rota em urls.py, uma nova variável em um .env, ou uma
    nova linha de log/configuração. Se o conteúdo precisar ser inserido no
    meio do arquivo, use 'edit_existing_file'.

    A ferramenta garante uma quebra de linha entre o que já existe e o que
    você adiciona. Se o conteúdo for SOMENTE imports (.py), eles são inseridos
    automaticamente junto aos imports do topo do arquivo, nunca no final. Em arquivos .py o resultado é validado (sintaxe e
    definições duplicadas): se a função/classe que você está adicionando JÁ
    EXISTE no arquivo, a operação é rejeitada — use 'edit_existing_file'.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a edição enquanto a
    branch atual for 'main' ou 'master'. Use 'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório. O sistema já
            resolve isso automaticamente contra o repositório correto — NÃO
            inclua o caminho absoluto do disco.
        content: O texto a ser adicionado ao final do arquivo, com a
            indentação real que deve ficar gravada.

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
        original_content, newline = _read_text_keep_newline(resolved_path)
    except (OSError, UnicodeDecodeError) as error:
        return f"ERRO ao ler o arquivo '{file_path}': {error}"

    addition = _strip_line_numbers_block(content).replace("\r\n", "\n")

    if resolved_path.suffix == ".py":
        inserted = _insert_imports_at_top(original_content, addition)
        if inserted is not None:
            merged, at_line, count = inserted
            if count == 0:
                return (
                    f"Nada a fazer: esses imports já existem em '{file_path}'. "
                    "O arquivo não foi alterado."
                )
            error, _warning = _validate_python_edit(original_content, merged)
            if error:
                return error
            try:
                _write_text_atomic(resolved_path, merged, newline)
            except OSError as exc:
                return f"ERRO ao adicionar imports em '{file_path}': {exc}"
            return (
                f"{count} import(s) adicionado(s) em '{file_path}' na linha {at_line}, "
                "junto aos imports do topo (imports nunca vão para o fim do arquivo). "
                "As linhas seguintes foram deslocadas; releia antes de usar números "
                "de linha posteriores."
            )

    if original_content and not original_content.endswith("\n") and not addition.startswith("\n"):
        addition = "\n" + addition

    new_content = original_content + addition
    if not new_content.endswith("\n"):
        new_content += "\n"

    if resolved_path.suffix == ".py":
        error, _warning = _validate_python_edit(original_content, new_content)
        if error:
            return error

    try:
        _write_text_atomic(resolved_path, new_content, newline)
    except OSError as error:
        return f"ERRO ao adicionar conteúdo ao arquivo '{file_path}': {error}"

    total = len(new_content.splitlines())
    return (
        f"Conteúdo adicionado ao final de '{file_path}' com sucesso. "
        f"O arquivo agora tem {total} linhas."
    )


@tool
def validate_python_syntax(file_path: str, runtime: ToolRuntime) -> str:
    """Verifica um arquivo Python: sintaxe, funções/classes duplicadas e avisos do pyflakes.

    Use depois de editar um .py, para confirmar que o arquivo não ficou quebrado.

    Args:
        file_path: Caminho relativo ao workspace do arquivo .py a ser verificado.

    Returns:
        Uma string com os problemas encontrados, ou uma confirmação de que está tudo certo.
    """
    workspace_path = runtime.state.get("workspace_path")

    if not workspace_path:
        return "ERRO: nenhum workspace definido para esta conversa."

    resolved_path = _resolve_path(file_path, workspace_path)

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe no workspace."

    if resolved_path.suffix != ".py":
        return "ERRO: apenas arquivos Python (.py) podem ser verificados."

    try:
        content, _newline = _read_text_keep_newline(resolved_path)
    except (OSError, UnicodeDecodeError) as error:
        return f"Erro ao ler o arquivo: {error}"

    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return _format_syntax_error(exc, content).replace(
            "(numeração do arquivo COMO FICARIA; nada foi salvo)\n", ""
        )

    issues: list[str] = []

    counts, _ = _collect_definitions(tree)
    for (scope, name), total in sorted(counts.items()):
        if total > 1:
            issues.append(
                f"DUPLICADO: '{name}' está definido {total}x em '{_scope_label(scope)}'."
            )

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyflakes", str(resolved_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if "No module named pyflakes" not in (result.stderr or ""):
            flakes = (result.stdout or "").strip()
            if flakes:
                issues.append("Avisos do pyflakes:\n" + flakes)
    except (OSError, subprocess.TimeoutExpired):
        pass

    if not issues:
        return "Nenhum erro de sintaxe, definição duplicada ou aviso encontrado."

    return "Problemas encontrados:\n" + "\n".join(issues)


# @tool
# def git_commit_changes(commit_message: str, files_to_commit: list[str], runtime: ToolRuntime) -> str:
#     """Cria um commit git APENAS com os arquivos especificados.

#     Use esta ferramenta SOMENTE no final da tarefa, depois de já ter feito
#     todas as edições necessárias com as outras ferramentas de escrita.

#     Você DEVE passar explicitamente a lista dos arquivos que VOCÊ modificou
#     ou criou. Nunca tente commitar arquivos em que você não trabalhou.

#     O commit só é permitido em branches de desenvolvimento (nunca em main/master).

#     A `commit_message` deve seguir o padrão Conventional Commits:
#     - 'feat: ...' para uma nova funcionalidade;
#     - 'fix: ...' para correção de bug;
#     - 'refactor: ...' para mudança de estrutura sem alterar comportamento;
#     - 'chore: ...' para tarefas de manutenção (configs, dependências);
#     - 'docs: ...' para mudanças em documentação.

#     Exemplo: 'docs: cria documentação técnica do módulo' 
#     (Nota: A tag de identificação da inteligência artificial [🤖 IA] será 
#     injetada automaticamente pelo sistema caso você não a inclua).

#     Args:
#         commit_message: Mensagem do commit seguindo Conventional Commits.
#         files_to_commit: Lista de strings com os caminhos relativos dos 
#             arquivos que você editou/criou.

#     Returns:
#         Uma mensagem de sucesso com a saída do commit, ou um erro detalhado.
#     """
#     workspace_path = runtime.state.get("workspace_path")

#     if not workspace_path:
#         return "ERRO: nenhum workspace definido para esta conversa."

#     repo = Path(workspace_path).resolve()

#     if not (repo / ".git").exists():
#         return f"ERRO: '{workspace_path}' não é a raiz de um repositório git."

#     if not files_to_commit:
#         return (
#             "ERRO: você deve fornecer a lista de arquivos "
#             "em 'files_to_commit'."
#         )

#     try:
#         branch_result = subprocess.run(
#             ["git", "branch", "--show-current"],
#             cwd=str(repo),
#             capture_output=True,
#             text=True,
#             timeout=10,
#         )

#         if branch_result.returncode != 0:
#             return (
#                 "ERRO DE SEGURANÇA: não foi possível verificar "
#                 "a branch atual."
#             )

#         current_branch = branch_result.stdout.strip()

#         if current_branch in {"main", "master"}:
#             return (
#                 f"ERRO DE SEGURANÇA: você não pode commitar diretamente "
#                 f"na branch '{current_branch}'. "
#                 "Crie uma branch de trabalho primeiro."
#             )

#         valid_files = []

#         for file_path in files_to_commit:
#             resolved_path = _resolve_path(file_path, workspace_path)

#             if not resolved_path.exists():
#                 return (
#                     f"ERRO: o arquivo '{file_path}' não existe "
#                     "no workspace."
#                 )

#             try:
#                 relative_path = resolved_path.relative_to(repo)
#             except ValueError:
#                 return (
#                     f"ERRO DE SEGURANÇA: o arquivo '{file_path}' "
#                     "está fora do workspace."
#                 )

#             valid_files.append(str(relative_path))

#         add_command = ["git", "add", "--"] + valid_files

#         add_result = subprocess.run(
#             add_command,
#             cwd=str(repo),
#             capture_output=True,
#             text=True,
#             timeout=30,
#         )

#         if add_result.returncode != 0:
#             return (
#                 "ERRO ao executar git add para os arquivos "
#                 f"({valid_files}): {add_result.stderr.strip()}"
#             )

#         clean_message = commit_message.strip()

#         if "[🤖 IA]" not in clean_message:
#             if ":" in clean_message:
#                 prefix, description = clean_message.split(":", 1)
#                 clean_message = (
#                     f"{prefix.strip()}: [🤖 IA] {description.strip()}"
#                 )
#             else:
#                 clean_message = f"[🤖 IA] {clean_message}"

#         commit_result = subprocess.run(
#             ["git", "commit", "-m", clean_message],
#             cwd=str(repo),
#             capture_output=True,
#             text=True,
#             timeout=30,
#         )

#         if commit_result.returncode != 0:
#             combined_output = (
#                 commit_result.stderr + commit_result.stdout
#             ).lower()

#             if "nothing to commit" in combined_output:
#                 return (
#                     "AVISO: não havia nenhuma alteração real "
#                     "nos arquivos especificados para commitar."
#                 )

#             return (
#                 "ERRO ao criar o commit: "
#                 f"{commit_result.stderr.strip() or commit_result.stdout.strip()}"
#             )

#         return (
#             f"Commit criado com sucesso na branch '{current_branch}'.\n"
#             f"Arquivos commitados: {', '.join(valid_files)}\n"
#             f"Mensagem: {clean_message}"
#         )

#     except FileNotFoundError:
#         return (
#             "ERRO: comando 'git' não encontrado. "
#             "Verifique se o Git está instalado e no PATH."
#         )

#     except subprocess.TimeoutExpired:
#         return (
#             "ERRO: o comando git demorou demais para responder "
#             "(timeout)."
#         )

#     except Exception as error:
#         return (
#             "ERRO inesperado na ferramenta de commit: "
#             f"{str(error)}"
#         )